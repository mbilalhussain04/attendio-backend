from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from uuid import UUID
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from app.models.attendance import (
    AttendanceEntry, AttendanceBreak, AttendanceFlag, AttendanceCorrectionRequest,
    AttendanceApproval, AttendanceLock, ShiftAssignment, GeofenceRule,
    NotificationEvent, OfflineSyncEvent, AttendanceExportJob, AttendanceSourceEvent,
    KioskDevice, AuditLog,
)
from app.services.policy_service import get_company_policy
from app.services.compliance_service import calculate_attendance_metrics, rest_period_violation
from app.services.audit_service import log_audit
from app.services.notification_service import queue_notification
from app.utils.geo import distance_meters
from app.utils.http import http_error
from app.utils.date import local_date_for, today_date


def _coerce_uuid(value):
    if isinstance(value, UUID) or value is None:
        return value
    return UUID(str(value))


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def _query_entry_full(db: Session, entry_id: str | UUID):
    return db.query(AttendanceEntry).options(
        joinedload(AttendanceEntry.breaks),
        joinedload(AttendanceEntry.flags),
        joinedload(AttendanceEntry.approvals),
        joinedload(AttendanceEntry.source_events),
    ).filter(AttendanceEntry.id == entry_id).first()


def get_open_attendance(db: Session, company_id: str, user_id: str):
    return db.query(AttendanceEntry).options(joinedload(AttendanceEntry.breaks), joinedload(AttendanceEntry.flags)).filter(
        AttendanceEntry.company_id == company_id,
        AttendanceEntry.user_id == user_id,
        AttendanceEntry.status == 'open',
    ).order_by(AttendanceEntry.check_in_at.desc()).first()


def is_locked(db: Session, company_id: str, target_date: date) -> bool:
    company_uuid = _coerce_uuid(company_id)
    row = db.query(AttendanceLock).filter(
        AttendanceLock.company_id == company_uuid,
        AttendanceLock.status == 'locked',
        AttendanceLock.from_date <= target_date,
        AttendanceLock.to_date >= target_date,
    ).first()
    return bool(row)


def rebuild_entry_metrics(db: Session, entry: AttendanceEntry):
    policy = get_company_policy(db, str(entry.company_id))
    breaks = db.query(AttendanceBreak).filter(AttendanceBreak.attendance_entry_id == entry.id).all()
    metrics = calculate_attendance_metrics(entry, breaks, policy)
    entry.worked_minutes = metrics['worked_minutes']
    entry.break_minutes = metrics['break_minutes']
    entry.overtime_minutes = metrics['overtime_minutes']
    entry.late_minutes = metrics['late_minutes']
    entry.early_departure_minutes = metrics['early_departure_minutes']
    db.query(AttendanceFlag).filter(AttendanceFlag.attendance_entry_id == entry.id).delete()
    for flag in metrics['flags']:
        db.add(AttendanceFlag(attendance_entry_id=entry.id, **flag))
    previous_entry = db.query(AttendanceEntry).filter(
        AttendanceEntry.company_id == entry.company_id,
        AttendanceEntry.user_id == entry.user_id,
        AttendanceEntry.check_out_at.is_not(None),
        AttendanceEntry.date < entry.date,
    ).order_by(AttendanceEntry.check_out_at.desc()).first()
    rest_flag = rest_period_violation(previous_entry, entry, policy)
    if rest_flag:
        db.add(AttendanceFlag(attendance_entry_id=entry.id, **rest_flag))
    db.flush()
    return _query_entry_full(db, entry.id)


def record_source_event(db: Session, company_id: str, attendance_entry_id: str | None, user_id: str | None, source: str, *, ip_address: str | None = None, latitude: float | None = None, longitude: float | None = None, metadata: dict | None = None):
    row = AttendanceSourceEvent(
        company_id=_coerce_uuid(company_id),
        attendance_entry_id=_coerce_uuid(attendance_entry_id),
        user_id=_coerce_uuid(user_id),
        source=source,
        ip_address=ip_address,
        latitude=latitude,
        longitude=longitude,
        metadata_json=metadata,
    )
    db.add(row)
    db.flush()
    return row


def validate_geofence(db: Session, company_id: str, branch_id: str | None, latitude: float | None, longitude: float | None):
    if latitude is None or longitude is None:
        return {'ok': True}
    q = db.query(GeofenceRule).filter(GeofenceRule.company_id == company_id, GeofenceRule.is_active.is_(True))
    if branch_id:
        q = q.filter(GeofenceRule.branch_id == branch_id)
    rules = q.all()
    if not rules:
        return {'ok': True}
    for rule in rules:
        if distance_meters(float(latitude), float(longitude), float(rule.latitude), float(rule.longitude)) <= int(rule.radius_meters):
            return {'ok': True, 'matched_rule_id': str(rule.id)}
    return {'ok': False, 'reason': 'Outside allowed geofence'}


def _profile_user(profile: dict | None) -> dict:
    return (profile or {}).get('user', profile or {}) or {}


def _employee_daily_target_minutes(profile: dict | None, policy) -> int:
    user = _profile_user(profile)
    expected_period = user.get('expected_hours_period') or ('monthly' if user.get('monthly_hours') else 'weekly')
    expected_hours = float(user.get('expected_hours') or 0)
    explicit_weekly = expected_hours if expected_period == 'weekly' and expected_hours else float(user.get('weekly_hours') or 0)
    explicit_monthly = expected_hours if expected_period == 'monthly' and expected_hours else float(user.get('monthly_hours') or 0)
    if explicit_weekly:
        return round(explicit_weekly * 60 / 5)
    if explicit_monthly:
        return round(explicit_monthly * 12 * 60 / 52 / 5)
    return round(float(policy.daily_target_hours) * 60)


def _shift_for_day(db: Session, company_id: str, user_id: str, target_date: date) -> ShiftAssignment | None:
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date, datetime.max.time())
    return db.query(ShiftAssignment).filter(
        ShiftAssignment.company_id == _coerce_uuid(company_id),
        ShiftAssignment.user_id == _coerce_uuid(user_id),
        ShiftAssignment.status != 'cancelled',
        ShiftAssignment.start_at <= end,
        ShiftAssignment.end_at >= start,
    ).order_by(ShiftAssignment.start_at.asc()).first()


def _schedule_target(db: Session, *, company_id: str, user_id: str, target_date: date, policy, profile: dict | None, scheduled_start_at, scheduled_end_at):
    start = _utc_naive(scheduled_start_at)
    end = _utc_naive(scheduled_end_at)
    if start and end:
        return start, end, max(int((end - start).total_seconds() // 60), 0)
    shift = _shift_for_day(db, company_id, user_id, target_date)
    if shift:
        target = max(int((shift.end_at - shift.start_at).total_seconds() // 60) - int(shift.break_minutes or 0), 0)
        return shift.start_at, shift.end_at, target
    return start, end, _employee_daily_target_minutes(profile, policy)


def check_in(db: Session, *, company_id: str, user_id: str, employee_code: str | None, branch_id: str | None, scheduled_start_at, scheduled_end_at, source: str, actor_user_id: str | None, latitude: float | None, longitude: float | None, ip_address: str | None, notes: str | None, check_in_at: datetime | None = None, profile: dict | None = None):
    target_time = _utc_naive(check_in_at) or datetime.utcnow()
    target_date = local_date_for(target_time)
    if is_locked(db, company_id, target_date):
        raise http_error(423, 'Attendance period is locked')
    existing = get_open_attendance(db, company_id, user_id)
    if existing:
        raise http_error(409, 'Open attendance session already exists')
    closed_today = db.query(AttendanceEntry).filter(
        AttendanceEntry.company_id == company_id,
        AttendanceEntry.user_id == user_id,
        AttendanceEntry.date == target_date,
        AttendanceEntry.check_out_at.is_not(None),
    ).first()
    if closed_today:
        raise http_error(409, 'Attendance day already closed. Use correction flow for changes.')
    geo = validate_geofence(db, company_id, branch_id, latitude, longitude)
    if not geo['ok']:
        raise http_error(403, geo['reason'])
    policy = get_company_policy(db, company_id)
    scheduled_start_at, scheduled_end_at, target_work_minutes = _schedule_target(
        db,
        company_id=company_id,
        user_id=user_id,
        target_date=target_date,
        policy=policy,
        profile=profile,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    entry = AttendanceEntry(
        company_id=company_id,
        user_id=user_id,
        employee_code=employee_code,
        branch_id=branch_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        source=source or 'web',
        check_in_at=target_time,
        date=target_date,
        target_work_minutes=target_work_minutes,
        notes=notes,
    )
    db.add(entry)
    db.flush()
    record_source_event(db, company_id, str(entry.id), user_id, source or 'web', ip_address=ip_address, latitude=latitude, longitude=longitude, metadata={'matchedRuleId': geo.get('matched_rule_id')})
    log_audit(db, company_id, actor_user_id, 'attendance.check_in', 'attendance_entry', str(entry.id), {'source': source})
    db.commit()
    return rebuild_entry_metrics(db, entry)
def check_out(db: Session, *, company_id: str, user_id: str, actor_user_id: str | None, latitude: float | None, longitude: float | None, ip_address: str | None, check_out_at: datetime | None = None):
    entry = get_open_attendance(db, company_id, user_id)
    if not entry:
        raise http_error(404, 'Open attendance session not found')
    target_time = _utc_naive(check_out_at) or datetime.utcnow()
    open_break = db.query(AttendanceBreak).filter(AttendanceBreak.attendance_entry_id == entry.id, AttendanceBreak.end_at.is_(None)).first()
    if open_break:
        open_break.end_at = target_time
        open_break.duration_minutes = max(int((open_break.end_at - open_break.start_at).total_seconds() // 60), 0)
    entry.check_out_at = target_time
    entry.status = 'closed'
    record_source_event(db, company_id, str(entry.id), user_id, entry.source, ip_address=ip_address, latitude=latitude, longitude=longitude)
    log_audit(db, company_id, actor_user_id, 'attendance.check_out', 'attendance_entry', str(entry.id))
    db.commit()
    rebuilt = rebuild_entry_metrics(db, entry)
    db.commit()
    return rebuilt


def start_break(db: Session, *, company_id: str, user_id: str, source: str, actor_user_id: str | None, start_at: datetime | None = None):
    entry = get_open_attendance(db, company_id, user_id)
    if not entry:
        raise http_error(404, 'Open attendance session not found')
    existing = db.query(AttendanceBreak).filter(AttendanceBreak.attendance_entry_id == entry.id, AttendanceBreak.end_at.is_(None)).first()
    if existing:
        raise http_error(409, 'Break already in progress')
    row = AttendanceBreak(attendance_entry_id=entry.id, start_at=_utc_naive(start_at) or datetime.utcnow(), source=source or 'web')
    db.add(row)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.break_start', 'attendance_break', str(row.id))
    db.commit()
    return row


def end_break(db: Session, *, company_id: str, user_id: str, actor_user_id: str | None, end_at: datetime | None = None):
    entry = get_open_attendance(db, company_id, user_id)
    if not entry:
        raise http_error(404, 'Open attendance session not found')
    row = db.query(AttendanceBreak).filter(AttendanceBreak.attendance_entry_id == entry.id, AttendanceBreak.end_at.is_(None)).first()
    if not row:
        raise http_error(404, 'No running break found')
    row.end_at = _utc_naive(end_at) or datetime.utcnow()
    row.duration_minutes = max(int((row.end_at - row.start_at).total_seconds() // 60), 0)
    log_audit(db, company_id, actor_user_id, 'attendance.break_end', 'attendance_break', str(row.id))
    db.commit()
    rebuild_entry_metrics(db, entry)
    db.commit()
    return row


def create_manual_entry(db: Session, *, company_id: str, user_id: str, employee_code: str | None, source: str, check_in_at: datetime, check_out_at: datetime, reason: str, branch_id: str | None, scheduled_start_at, scheduled_end_at, actor_user_id: str | None, notes: str | None, break_minutes: int = 0, profile: dict | None = None):
    company_uuid = _coerce_uuid(company_id)
    user_uuid = _coerce_uuid(user_id)
    actor_uuid = _coerce_uuid(actor_user_id)
    branch_uuid = _coerce_uuid(branch_id)
    target_date = local_date_for(check_in_at)
    if target_date > today_date():
        raise http_error(400, 'Manual entries cannot be submitted for future dates')
    if local_date_for(check_out_at) != target_date:
        raise http_error(400, 'Manual entries must start and end on the same date')
    check_in_at = _utc_naive(check_in_at)
    check_out_at = _utc_naive(check_out_at)
    policy = get_company_policy(db, str(company_uuid))
    scheduled_start_at, scheduled_end_at, target_work_minutes = _schedule_target(
        db,
        company_id=str(company_uuid),
        user_id=str(user_uuid),
        target_date=target_date,
        policy=policy,
        profile=profile,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    if is_locked(db, company_uuid, target_date):
        raise http_error(423, 'Attendance period is locked')
    gross_minutes = max(int((check_out_at - check_in_at).total_seconds() // 60), 0)
    if gross_minutes <= 0:
        raise http_error(400, 'Check-out time must be after check-in time')
    if break_minutes < 0 or break_minutes >= gross_minutes:
        raise http_error(400, 'Break time must be less than the total attendance span')
    existing = db.query(AttendanceEntry).filter(
        AttendanceEntry.company_id == company_uuid,
        AttendanceEntry.user_id == user_uuid,
        AttendanceEntry.date == target_date,
    ).first()
    if existing:
        raise http_error(409, 'Attendance already exists for this date. Use reset or correction flow for changes.')
    row = AttendanceEntry(
        company_id=company_uuid, user_id=user_uuid, employee_code=employee_code, source=source or 'manual', branch_id=branch_uuid,
        check_in_at=check_in_at, check_out_at=check_out_at, date=target_date, status='corrected', manual_reason=reason,
        scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at, target_work_minutes=target_work_minutes, notes=notes,
    )
    db.add(row)
    db.flush()
    if break_minutes:
        break_start = check_in_at + timedelta(minutes=max((gross_minutes - break_minutes) // 2, 0))
        db.add(AttendanceBreak(attendance_entry_id=row.id, start_at=break_start, end_at=break_start + timedelta(minutes=break_minutes), duration_minutes=break_minutes, source='manual'))
    db.add(AttendanceFlag(attendance_entry_id=row.id, flag_type='manual_entry', severity='info', message='Manual entry created'))
    log_audit(db, str(company_uuid), str(actor_uuid) if actor_uuid else None, 'attendance.manual_entry', 'attendance_entry', str(row.id), {'reason': reason})
    db.commit()
    return rebuild_entry_metrics(db, row)


def submit_self_entry(db: Session, *, company_id: str, user_id: str, employee_code: str | None, check_in_at: datetime, check_out_at: datetime, reason: str, branch_id: str | None, scheduled_start_at, scheduled_end_at, actor_user_id: str | None, notes: str | None, break_minutes: int = 0, profile: dict | None = None):
    row = create_manual_entry(
        db,
        company_id=company_id,
        user_id=user_id,
        employee_code=employee_code,
        source='manual_self',
        check_in_at=check_in_at,
        check_out_at=check_out_at,
        reason=reason,
        branch_id=branch_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        actor_user_id=actor_user_id,
        notes=notes,
        break_minutes=break_minutes,
        profile=profile,
    )
    log_audit(db, company_id, actor_user_id, 'attendance.recorded', 'attendance_entry', str(row.id), {'reason': reason})
    db.commit()
    return rebuild_entry_metrics(db, row)


def list_self_corrections(db: Session, company_id: str, user_id: str):
    return db.query(AttendanceCorrectionRequest).options(joinedload(AttendanceCorrectionRequest.entry)).filter(
        AttendanceCorrectionRequest.company_id == _coerce_uuid(company_id),
        AttendanceCorrectionRequest.requested_by_user_id == _coerce_uuid(user_id),
    ).order_by(AttendanceCorrectionRequest.created_at.desc()).all()


def list_pending_corrections(db: Session, company_id: str):
    return db.query(AttendanceCorrectionRequest).options(joinedload(AttendanceCorrectionRequest.entry)).filter(
        AttendanceCorrectionRequest.company_id == _coerce_uuid(company_id),
    ).order_by(AttendanceCorrectionRequest.created_at.desc()).all()


def list_pending_submissions(db: Session, company_id: str):
    return db.query(AttendanceEntry).options(joinedload(AttendanceEntry.approvals)).filter(
        AttendanceEntry.company_id == company_id,
        AttendanceEntry.status == 'submitted',
    ).order_by(AttendanceEntry.date.asc()).all()


def review_submission(db: Session, *, company_id: str, attendance_entry_id: str, approver_user_id: str, status: str, decision_reason: str | None):
    company_uuid = _coerce_uuid(company_id)
    entry_uuid = _coerce_uuid(attendance_entry_id)
    approver_uuid = _coerce_uuid(approver_user_id)
    entry = db.query(AttendanceEntry).filter(AttendanceEntry.id == entry_uuid, AttendanceEntry.company_id == company_uuid, AttendanceEntry.status == 'submitted').first()
    if not entry:
        raise http_error(404, 'Submitted attendance entry not found')
    entry.status = status
    approval = db.query(AttendanceApproval).filter(
        AttendanceApproval.company_id == company_uuid,
        AttendanceApproval.attendance_entry_id == entry_uuid,
        AttendanceApproval.status == 'pending',
    ).first()
    if approval:
        approval.status = status
        approval.approver_user_id = approver_uuid
        approval.decision_reason = decision_reason
    log_audit(db, str(company_uuid), str(approver_uuid), f'attendance.submission_{status}', 'attendance_entry', str(entry.id), {'reason': decision_reason})
    db.commit()
    return rebuild_entry_metrics(db, entry)


def list_locks(db: Session, company_id: str):
    return db.query(AttendanceLock).filter(AttendanceLock.company_id == company_id).order_by(AttendanceLock.created_at.desc()).all()


def reset_self_date(db: Session, *, company_id: str, user_id: str, target_date: date, actor_user_id: str):
    company_uuid = _coerce_uuid(company_id)
    user_uuid = _coerce_uuid(user_id)
    actor_uuid = _coerce_uuid(actor_user_id)
    if target_date > today_date():
        raise http_error(400, 'Future dates cannot be reset')
    if is_locked(db, company_uuid, target_date):
        raise http_error(423, 'Attendance period is locked')
    rows = db.query(AttendanceEntry).filter(
        AttendanceEntry.company_id == company_uuid,
        AttendanceEntry.user_id == user_uuid,
        AttendanceEntry.date == target_date,
    ).all()
    entry_ids = [row.id for row in rows]
    count = len(entry_ids)
    if entry_ids:
        db.query(AttendanceBreak).filter(AttendanceBreak.attendance_entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(AttendanceFlag).filter(AttendanceFlag.attendance_entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(AttendanceCorrectionRequest).filter(AttendanceCorrectionRequest.attendance_entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(AttendanceApproval).filter(AttendanceApproval.attendance_entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(AttendanceSourceEvent).filter(AttendanceSourceEvent.attendance_entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(AttendanceEntry).filter(AttendanceEntry.id.in_(entry_ids)).delete(synchronize_session=False)
    log_audit(db, str(company_uuid), str(actor_uuid), 'attendance.reset_self_date', 'attendance_entry', None, {'date': str(target_date), 'deletedCount': count})
    db.commit()
    return {'date': str(target_date), 'deleted_count': count}


def request_correction(db: Session, *, company_id: str, requested_by_user_id: str, attendance_entry_id: str, reason: str, requested_check_in_at, requested_check_out_at, requested_break_minutes: int | None = None, correction_type: str | None = None, requester_timezone: str | None = None):
    company_uuid = _coerce_uuid(company_id)
    requested_by_uuid = _coerce_uuid(requested_by_user_id)
    entry_uuid = _coerce_uuid(attendance_entry_id)
    entry = db.query(AttendanceEntry).filter(AttendanceEntry.id == entry_uuid, AttendanceEntry.company_id == company_uuid).first()
    if not entry:
        raise http_error(404, 'Attendance entry not found')
    existing_pending = db.query(AttendanceCorrectionRequest).filter(
        AttendanceCorrectionRequest.company_id == company_uuid,
        AttendanceCorrectionRequest.attendance_entry_id == entry_uuid,
        AttendanceCorrectionRequest.status == 'pending',
    ).first()
    if existing_pending:
        raise http_error(409, 'A correction request is already pending for this attendance entry')
    requested_check_in_at = _utc_naive(requested_check_in_at)
    requested_check_out_at = _utc_naive(requested_check_out_at)
    if requested_check_in_at is None and requested_check_out_at is None and requested_break_minutes is None:
        raise http_error(400, 'Select at least one correction value')
    if requested_break_minutes is not None:
        check_in = requested_check_in_at or entry.check_in_at
        check_out = requested_check_out_at or entry.check_out_at
        if not check_in or not check_out:
            raise http_error(400, 'Break correction requires check-in and check-out times')
        gross_minutes = max(int((check_out - check_in).total_seconds() // 60), 0)
        if requested_break_minutes >= gross_minutes:
            raise http_error(400, 'Break time must be less than the total attendance span')
    row = AttendanceCorrectionRequest(
        attendance_entry_id=entry_uuid, company_id=company_uuid, requested_by_user_id=requested_by_uuid,
        correction_type=correction_type,
        requester_timezone=requester_timezone,
        reason=reason, requested_check_in_at=requested_check_in_at, requested_check_out_at=requested_check_out_at,
        requested_break_minutes=requested_break_minutes,
        original_check_in_at=entry.check_in_at,
        original_check_out_at=entry.check_out_at,
        original_break_minutes=entry.break_minutes or 0,
        entry_date=entry.date,
    )
    db.add(row)
    db.flush()
    db.add(AttendanceApproval(company_id=company_uuid, attendance_entry_id=entry_uuid, level=1, status='pending'))
    log_audit(db, str(company_uuid), str(requested_by_uuid), 'attendance.correction_requested', 'attendance_correction_request', str(row.id), {'correctionType': correction_type, 'requesterTimezone': requester_timezone})
    queue_notification(db, str(company_uuid), 'correction_request', {'attendanceEntryId': str(entry_uuid), 'reason': reason, 'correctionType': correction_type, 'requesterTimezone': requester_timezone}, user_id=str(requested_by_uuid))
    db.commit()
    return row


def review_correction(db: Session, *, company_id: str, correction_request_id: str, approver_user_id: str, status: str, decision_reason: str | None):
    company_uuid = _coerce_uuid(company_id)
    correction_uuid = _coerce_uuid(correction_request_id)
    approver_uuid = _coerce_uuid(approver_user_id)
    correction = db.query(AttendanceCorrectionRequest).filter(AttendanceCorrectionRequest.id == correction_uuid, AttendanceCorrectionRequest.company_id == company_uuid).first()
    if not correction:
        raise http_error(404, 'Correction request not found')
    correction.status = status
    correction.decision_reason = decision_reason
    correction.reviewed_by_user_id = approver_uuid
    approval = db.query(AttendanceApproval).filter(AttendanceApproval.company_id == company_uuid, AttendanceApproval.attendance_entry_id == correction.attendance_entry_id, AttendanceApproval.status == 'pending').order_by(AttendanceApproval.level.asc()).first()
    if approval:
        approval.status = status
        approval.approver_user_id = approver_uuid
        approval.decision_reason = decision_reason
    if status == 'approved':
        entry = db.query(AttendanceEntry).filter(AttendanceEntry.id == correction.attendance_entry_id).first()
        if correction.requested_check_in_at:
            entry.check_in_at = correction.requested_check_in_at
        if correction.requested_check_out_at:
            entry.check_out_at = correction.requested_check_out_at
        if correction.requested_break_minutes is not None:
            db.query(AttendanceBreak).filter(AttendanceBreak.attendance_entry_id == entry.id).delete()
            gross_minutes = max(int((entry.check_out_at - entry.check_in_at).total_seconds() // 60), 0) if entry.check_in_at and entry.check_out_at else 0
            if correction.requested_break_minutes and gross_minutes:
                break_start = entry.check_in_at + timedelta(minutes=max((gross_minutes - correction.requested_break_minutes) // 2, 0))
                db.add(AttendanceBreak(attendance_entry_id=entry.id, start_at=break_start, end_at=break_start + timedelta(minutes=correction.requested_break_minutes), duration_minutes=correction.requested_break_minutes, source='correction'))
            db.flush()
        entry.status = 'corrected'
        rebuild_entry_metrics(db, entry)
    log_audit(db, str(company_uuid), str(approver_uuid), f'attendance.correction_{status}', 'attendance_correction_request', str(correction.id))
    db.commit()
    return correction


def bulk_review_corrections(db: Session, *, company_id: str, ids: list[str], approver_user_id: str, status: str, decision_reason: str | None):
    results = []
    for item in ids:
        results.append(review_correction(db, company_id=company_id, correction_request_id=str(item), approver_user_id=approver_user_id, status=status, decision_reason=decision_reason))
    return results


def lock_period(db: Session, *, company_id: str, from_date: date, to_date: date, locked_by_user_id: str, reason: str | None):
    row = AttendanceLock(company_id=company_id, from_date=from_date, to_date=to_date, locked_by_user_id=locked_by_user_id, reason=reason)
    db.add(row)
    db.flush()
    db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.date >= from_date, AttendanceEntry.date <= to_date, AttendanceEntry.status != 'open').update({'status': 'locked'}, synchronize_session=False)
    log_audit(db, company_id, locked_by_user_id, 'attendance.lock_period', 'attendance_lock', str(row.id), {'fromDate': str(from_date), 'toDate': str(to_date)})
    db.commit()
    return row


def unlock_period(db: Session, *, company_id: str, lock_id: str, actor_user_id: str):
    row = db.query(AttendanceLock).filter(AttendanceLock.id == lock_id, AttendanceLock.company_id == company_id).first()
    if not row:
        raise http_error(404, 'Lock not found')
    row.status = 'unlocked'
    db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.date >= row.from_date, AttendanceEntry.date <= row.to_date, AttendanceEntry.status == 'locked').update({'status': 'closed'}, synchronize_session=False)
    log_audit(db, company_id, actor_user_id, 'attendance.unlock_period', 'attendance_lock', str(row.id))
    db.commit()
    return row


def assign_shift(db: Session, *, company_id: str, actor_user_id: str, payload: dict):
    row = ShiftAssignment(company_id=company_id, **payload)
    db.add(row)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.shift_assigned', 'shift_assignment', str(row.id))
    db.commit()
    return row


def update_shift(db: Session, *, company_id: str, shift_id: str, actor_user_id: str, payload: dict):
    row = db.query(ShiftAssignment).filter(
        ShiftAssignment.company_id == _coerce_uuid(company_id),
        ShiftAssignment.id == _coerce_uuid(shift_id),
    ).first()
    if not row:
        raise http_error(404, 'Shift not found')
    for key, value in payload.items():
        setattr(row, key, value)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.shift_updated', 'shift_assignment', str(row.id))
    db.commit()
    return row


def delete_shift(db: Session, *, company_id: str, shift_id: str, actor_user_id: str):
    row = db.query(ShiftAssignment).filter(
        ShiftAssignment.company_id == _coerce_uuid(company_id),
        ShiftAssignment.id == _coerce_uuid(shift_id),
    ).first()
    if not row:
        raise http_error(404, 'Shift not found')
    db.delete(row)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.shift_deleted', 'shift_assignment', str(row.id))
    db.commit()
    return {'id': str(row.id), 'deleted': True}


def list_shifts(db: Session, company_id: str, filters: dict | None = None):
    q = db.query(ShiftAssignment).filter(ShiftAssignment.company_id == company_id)
    if filters and filters.get('user_id'):
        q = q.filter(ShiftAssignment.user_id == filters['user_id'])
    return q.order_by(ShiftAssignment.start_at.asc()).all()


def create_kiosk_device(db: Session, *, company_id: str, actor_user_id: str, payload: dict):
    row = KioskDevice(company_id=company_id, **payload)
    db.add(row)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.kiosk_device_created', 'kiosk_device', str(row.id))
    db.commit()
    return row


def update_kiosk_device(db: Session, *, company_id: str, device_id: str, actor_user_id: str, payload: dict):
    row = db.query(KioskDevice).filter(KioskDevice.company_id == _coerce_uuid(company_id), KioskDevice.id == _coerce_uuid(device_id)).first()
    if not row:
        raise http_error(404, 'Kiosk device not found')
    for key, value in payload.items():
        setattr(row, key, value)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.kiosk_device_updated', 'kiosk_device', str(row.id))
    db.commit()
    return row


def delete_kiosk_device(db: Session, *, company_id: str, device_id: str, actor_user_id: str):
    row = db.query(KioskDevice).filter(KioskDevice.company_id == _coerce_uuid(company_id), KioskDevice.id == _coerce_uuid(device_id)).first()
    if not row:
        raise http_error(404, 'Kiosk device not found')
    db.delete(row)
    db.flush()
    log_audit(db, company_id, actor_user_id, 'attendance.kiosk_device_deleted', 'kiosk_device', str(row.id))
    db.commit()
    return {'id': str(row.id), 'deleted': True}


def list_kiosk_devices(db: Session, company_id: str):
    return db.query(KioskDevice).filter(KioskDevice.company_id == company_id).order_by(KioskDevice.created_at.desc()).all()


def kiosk_check_in(db: Session, *, company_id: str, actor_user_id: str, user_id: str, employee_code: str | None, branch_id: str | None, kiosk_device_id: str | None, notes: str | None):
    entry = check_in(db, company_id=company_id, user_id=user_id, employee_code=employee_code, branch_id=branch_id, scheduled_start_at=None, scheduled_end_at=None, source='kiosk', actor_user_id=actor_user_id, latitude=None, longitude=None, ip_address=None, notes=notes)
    record_source_event(db, company_id, str(entry.id), user_id, 'kiosk', metadata={'kioskDeviceId': kiosk_device_id})
    db.commit()
    return _query_entry_full(db, entry.id)


def queue_offline_sync(db: Session, *, company_id: str, user_id: str | None, source: str, payload: dict):
    row = OfflineSyncEvent(company_id=company_id, user_id=user_id, source=source, payload=payload, status='pending')
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def process_offline_sync_event(db: Session, event_id: str):
    row = db.query(OfflineSyncEvent).filter(OfflineSyncEvent.id == event_id).first()
    if not row:
        raise http_error(404, 'Offline sync event not found')
    row.status = 'processed'
    row.synced_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def get_today_for_user(db: Session, company_id: str, user_id: str):
    return db.query(AttendanceEntry).options(joinedload(AttendanceEntry.breaks), joinedload(AttendanceEntry.flags), joinedload(AttendanceEntry.approvals), joinedload(AttendanceEntry.source_events)).filter(
        AttendanceEntry.company_id == company_id,
        AttendanceEntry.user_id == user_id,
        AttendanceEntry.date == today_date(),
    ).order_by(AttendanceEntry.check_in_at.asc()).all()


def get_timesheet(db: Session, company_id: str, user_id: str, start: date, end: date):
    return db.query(AttendanceEntry).options(joinedload(AttendanceEntry.breaks), joinedload(AttendanceEntry.flags), joinedload(AttendanceEntry.approvals)).filter(
        AttendanceEntry.company_id == company_id,
        AttendanceEntry.user_id == user_id,
        AttendanceEntry.date >= start,
        AttendanceEntry.date <= end,
    ).order_by(AttendanceEntry.date.asc(), AttendanceEntry.check_in_at.asc()).all()


def get_who_is_in(db: Session, company_id: str, branch_id: str | None = None):
    q = db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.status == 'open')
    if branch_id:
        q = q.filter(AttendanceEntry.branch_id == branch_id)
    return q.order_by(AttendanceEntry.check_in_at.asc()).all()


def get_daily_summary(db: Session, company_id: str, target_date: date, branch_id: str | None = None):
    q = db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.date == target_date)
    if branch_id:
        q = q.filter(AttendanceEntry.branch_id == branch_id)
    entries = q.all()
    return {
        'date': str(target_date),
        'totalEntries': len(entries),
        'open': sum(1 for e in entries if e.status == 'open'),
        'late': sum(1 for e in entries if int(e.late_minutes or 0) > 0),
        'early': sum(1 for e in entries if int(e.early_departure_minutes or 0) > 0),
        'absent': 0,
        'workedMinutes': sum(int(e.worked_minutes or 0) for e in entries),
    }


def get_dashboard(db: Session, company_id: str, target_date: date, branch_id: str | None = None):
    summary = get_daily_summary(db, company_id, target_date, branch_id)
    who_is_in = get_who_is_in(db, company_id, branch_id)
    pending_corrections = db.query(AttendanceCorrectionRequest).filter(AttendanceCorrectionRequest.company_id == company_id, AttendanceCorrectionRequest.status == 'pending').count()
    pending_notifications = db.query(NotificationEvent).filter(NotificationEvent.company_id == company_id, NotificationEvent.status == 'queued').count()
    return {'summary': summary, 'whoIsInCount': len(who_is_in), 'pendingCorrections': pending_corrections, 'pendingNotifications': pending_notifications}


def grouped_report(db: Session, company_id: str, start: date, end: date):
    return db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.date >= start, AttendanceEntry.date <= end).order_by(AttendanceEntry.date.asc(), AttendanceEntry.user_id.asc()).all()


def get_weekly_report(db: Session, company_id: str, start: date, end: date):
    return grouped_report(db, company_id, start, end)


def get_monthly_report(db: Session, company_id: str, start: date, end: date):
    return grouped_report(db, company_id, start, end)


def get_overtime_report(db: Session, company_id: str, start: date, end: date):
    return [e for e in grouped_report(db, company_id, start, end) if int(e.overtime_minutes or 0) > 0]


def get_absence_analysis(db: Session, company_id: str, start: date, end: date):
    entries = grouped_report(db, company_id, start, end)
    by_type = {}
    for e in entries:
        key = e.absence_type or 'none'
        by_type[key] = by_type.get(key, 0) + 1
    return {'range': [str(start), str(end)], 'byType': by_type}


def get_branch_comparison(db: Session, company_id: str, start: date, end: date):
    entries = grouped_report(db, company_id, start, end)
    buckets = {}
    for e in entries:
        key = str(e.branch_id) if e.branch_id else 'unassigned'
        item = buckets.setdefault(key, {'branchId': key, 'totalEntries': 0, 'workedMinutes': 0, 'overtimeMinutes': 0})
        item['totalEntries'] += 1
        item['workedMinutes'] += int(e.worked_minutes or 0)
        item['overtimeMinutes'] += int(e.overtime_minutes or 0)
    return list(buckets.values())


def get_shift_variance_report(db: Session, company_id: str, start: date, end: date):
    shifts = db.query(ShiftAssignment).filter(ShiftAssignment.company_id == company_id, ShiftAssignment.start_at >= datetime.combine(start, datetime.min.time()), ShiftAssignment.start_at <= datetime.combine(end, datetime.max.time())).all()
    report = []
    for shift in shifts:
        entry = db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.user_id == shift.user_id, AttendanceEntry.date == shift.start_at.date()).first()
        scheduled = max(int((shift.end_at - shift.start_at).total_seconds() // 60) - int(shift.break_minutes or 0), 0)
        actual = int(entry.worked_minutes or 0) if entry else 0
        report.append({'shiftId': str(shift.id), 'userId': str(shift.user_id), 'shiftName': shift.name, 'scheduledMinutes': scheduled, 'actualMinutes': actual, 'varianceMinutes': actual - scheduled})
    return report


def get_anomaly_report(db: Session, company_id: str, start: date, end: date):
    return db.query(AttendanceEntry).options(joinedload(AttendanceEntry.flags)).filter(AttendanceEntry.company_id == company_id, AttendanceEntry.date >= start, AttendanceEntry.date <= end).all()


def queue_export_job(db: Session, *, company_id: str, requested_by_user_id: str, format: str, from_date: date, to_date: date, filters: dict | None):
    row = AttendanceExportJob(company_id=company_id, requested_by_user_id=requested_by_user_id, format=format, from_date=from_date, to_date=to_date, filters=filters, status='queued')
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def complete_export_job(db: Session, job_id: str):
    job = db.query(AttendanceExportJob).filter(AttendanceExportJob.id == job_id).first()
    if not job:
        raise http_error(404, 'Export job not found')
    job.status = 'completed'
    job.output_path = f"/exports/{job.id}.{'xlsx' if job.format == 'excel' else 'json'}"
    db.commit()
    db.refresh(job)
    return job


def list_audit_logs(db: Session, company_id: str, limit: int = 100):
    return db.query(AuditLog).filter(AuditLog.company_id == company_id).order_by(AuditLog.created_at.desc()).limit(limit).all()
