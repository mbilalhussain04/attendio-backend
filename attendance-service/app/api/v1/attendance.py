from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.deps.db import get_db
from app.deps.auth import get_auth_context, require_permissions, AuthContext
from app.schemas.common import StandardResponse
from app.schemas.attendance import *
from app.services import attendance_service
from app.services.policy_service import get_company_policy, update_company_policy, list_holidays, upsert_holiday, update_holiday, delete_holiday, import_public_holidays
from app.models.attendance import GeofenceRule, NotificationEvent, AttendanceExportJob
from app.utils.permissions import Permissions
from app.utils.date import parse_range, today_date
from io import BytesIO
import csv
import httpx

router = APIRouter(prefix='/api/v1/attendance')


def ok(data, message: str | None = None):
    payload = {'success': True, 'data': data}
    if message:
        payload['message'] = message
    return payload


@router.post('/check-in', tags=['Attendance'])
def check_in(payload: CheckInIn, request: Request, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_CHECK_IN))):
    row = attendance_service.check_in(db, company_id=auth.company_id, user_id=auth.user_id, employee_code=auth.profile.get('employee_code') if auth.profile else payload.employee_code, branch_id=str(payload.branch_id) if payload.branch_id else (str(auth.profile.get('branch_id')) if auth.profile and auth.profile.get('branch_id') else None), scheduled_start_at=payload.scheduled_start_at, scheduled_end_at=payload.scheduled_end_at, source=payload.source, actor_user_id=auth.user_id, latitude=payload.latitude, longitude=payload.longitude, ip_address=request.client.host if request.client else None, notes=payload.notes, check_in_at=payload.check_in_at, profile=auth.profile)
    return ok(AttendanceEntryOut.model_validate(row), f"Check in successful for {auth.profile.get('first_name') + ' ' + auth.profile.get('last_name') if auth.profile and auth.profile.get('first_name') else auth.email or auth.user_id}")


@router.post('/check-out', tags=['Attendance'])
def check_out(payload: CheckOutIn, request: Request, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_CHECK_OUT))):
    row = attendance_service.check_out(db, company_id=auth.company_id, user_id=auth.user_id, actor_user_id=auth.user_id, latitude=payload.latitude, longitude=payload.longitude, ip_address=request.client.host if request.client else None, check_out_at=payload.check_out_at)
    return ok(AttendanceEntryOut.model_validate(row))


@router.post('/breaks/start', tags=['Attendance'])
def start_break(payload: StartBreakIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_BREAK_START))):
    row = attendance_service.start_break(db, company_id=auth.company_id, user_id=auth.user_id, source=payload.source, actor_user_id=auth.user_id, start_at=payload.start_at)
    return ok(BreakOut.model_validate(row))


@router.post('/breaks/end', tags=['Attendance'])
def end_break(payload: EndBreakIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_BREAK_END))):
    row = attendance_service.end_break(db, company_id=auth.company_id, user_id=auth.user_id, actor_user_id=auth.user_id, end_at=payload.end_at)
    return ok(BreakOut.model_validate(row))


@router.post('/entries/manual', tags=['Attendance'])
def manual_entry(payload: ManualEntryIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_MANUAL_ENTRY))):
    row = attendance_service.create_manual_entry(db, company_id=auth.company_id, user_id=str(payload.user_id or auth.user_id), employee_code=payload.employee_code, branch_id=str(payload.branch_id) if payload.branch_id else None, check_in_at=payload.check_in_at, check_out_at=payload.check_out_at, scheduled_start_at=payload.scheduled_start_at, scheduled_end_at=payload.scheduled_end_at, reason=payload.reason, source='manual', actor_user_id=auth.user_id, notes=payload.notes, break_minutes=payload.break_minutes)
    return ok(AttendanceEntryOut.model_validate(row))


@router.post('/me/entries/manual', tags=['Attendance'])
def self_manual_entry(payload: ManualEntryIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    row = attendance_service.submit_self_entry(
        db,
        company_id=auth.company_id,
        user_id=auth.user_id,
        employee_code=auth.profile.get('employee_code') if auth.profile else payload.employee_code,
        branch_id=str(auth.profile.get('branch_id')) if auth.profile and auth.profile.get('branch_id') else None,
        check_in_at=payload.check_in_at,
        check_out_at=payload.check_out_at,
        scheduled_start_at=payload.scheduled_start_at,
        scheduled_end_at=payload.scheduled_end_at,
        reason=payload.reason,
        actor_user_id=auth.user_id,
        notes=payload.notes,
        break_minutes=payload.break_minutes,
        profile=auth.profile,
    )
    return ok(AttendanceEntryOut.model_validate(row))


@router.post('/corrections', tags=['Corrections'])
def correction_request(payload: CorrectionRequestIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    row = attendance_service.request_correction(db, company_id=auth.company_id, requested_by_user_id=auth.user_id, attendance_entry_id=str(payload.attendance_entry_id), correction_type=payload.correction_type, reason=payload.reason, requested_check_in_at=payload.requested_check_in_at, requested_check_out_at=payload.requested_check_out_at, requested_break_minutes=payload.requested_break_minutes, requester_timezone=payload.requester_timezone)
    return ok(CorrectionOut.model_validate(row))


@router.post('/corrections/review', tags=['Corrections'])
def review_correction(payload: CorrectionReviewIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_APPROVE))):
    row = attendance_service.review_correction(db, company_id=auth.company_id, correction_request_id=str(payload.correction_request_id), approver_user_id=auth.user_id, status=payload.status, decision_reason=payload.decision_reason)
    return ok(CorrectionOut.model_validate(row))


@router.post('/corrections/review/bulk', tags=['Corrections'])
def bulk_review(payload: BulkCorrectionReviewIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_APPROVE))):
    rows = attendance_service.bulk_review_corrections(db, company_id=auth.company_id, ids=[str(v) for v in payload.ids], approver_user_id=auth.user_id, status=payload.status, decision_reason=payload.decision_reason)
    return ok([CorrectionOut.model_validate(r) for r in rows])


@router.get('/corrections/me', tags=['Corrections'])
def self_corrections(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    return ok([CorrectionOut.model_validate(r) for r in attendance_service.list_self_corrections(db, auth.company_id, auth.user_id)])


@router.get('/corrections/pending', tags=['Corrections'])
def pending_corrections(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_APPROVE))):
    return ok([CorrectionOut.model_validate(r) for r in attendance_service.list_pending_corrections(db, auth.company_id)])


@router.get('/submissions/pending', tags=['Approvals'])
def pending_submissions(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_APPROVE))):
    return ok([AttendanceEntryOut.model_validate(r) for r in attendance_service.list_pending_submissions(db, auth.company_id)])


@router.post('/submissions/review', tags=['Approvals'])
def review_submission(payload: SubmissionReviewIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_APPROVE))):
    row = attendance_service.review_submission(db, company_id=auth.company_id, attendance_entry_id=str(payload.attendance_entry_id), approver_user_id=auth.user_id, status=payload.status, decision_reason=payload.decision_reason)
    return ok(AttendanceEntryOut.model_validate(row))


@router.post('/locks', tags=['Compliance'])
def lock_period(payload: LockPeriodIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_LOCK))):
    row = attendance_service.lock_period(db, company_id=auth.company_id, from_date=payload.from_date, to_date=payload.to_date, locked_by_user_id=auth.user_id, reason=payload.reason)
    return ok({'id': str(row.id), 'status': row.status, 'from_date': str(row.from_date), 'to_date': str(row.to_date)})


@router.get('/locks', tags=['Compliance'])
def locks(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_LOCK))):
    return ok([LockOut.model_validate(r) for r in attendance_service.list_locks(db, auth.company_id)])


@router.post('/locks/unlock', tags=['Compliance'])
def unlock_period(payload: UnlockPeriodIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_LOCK))):
    row = attendance_service.unlock_period(db, company_id=auth.company_id, lock_id=str(payload.lock_id), actor_user_id=auth.user_id)
    return ok({'id': str(row.id), 'status': row.status})


@router.get('/me/today', tags=['Attendance'])
def me_today(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    rows = attendance_service.get_today_for_user(db, auth.company_id, auth.user_id)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/me/open', tags=['Attendance'])
def me_open(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    row = attendance_service.get_open_attendance(db, auth.company_id, auth.user_id)
    return ok(AttendanceEntryOut.model_validate(row) if row else None)


@router.post('/me/entries/reset', tags=['Attendance'])
def reset_my_date(payload: ResetSelfDateIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_MANUAL_ENTRY))):
    return ok(attendance_service.reset_self_date(db, company_id=auth.company_id, user_id=auth.user_id, target_date=payload.target_date, actor_user_id=auth.user_id))


@router.get('/me/timesheet', tags=['Attendance'])
def me_timesheet(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    start, end = parse_range(from_date, to_date)
    rows = attendance_service.get_timesheet(db, auth.company_id, auth.user_id, start, end)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/users/{user_id}/timesheet', tags=['Attendance'])
def user_timesheet(user_id: str, from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    rows = attendance_service.get_timesheet(db, auth.company_id, user_id, start, end)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/dashboard', tags=['Reports'])
def dashboard(target_date: date | None = Query(None, alias='date'), branch_id: str | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    return ok(attendance_service.get_dashboard(db, auth.company_id, target_date or today_date(), branch_id))


@router.get('/who-is-in', tags=['Reports'])
def who_is_in(branch_id: str | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_TEAM))):
    rows = attendance_service.get_who_is_in(db, auth.company_id, branch_id)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/summary/daily', tags=['Reports'])
def daily_summary(target_date: date | None = Query(None, alias='date'), branch_id: str | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    return ok(attendance_service.get_daily_summary(db, auth.company_id, target_date or today_date(), branch_id))


@router.get('/reports/weekly', tags=['Reports'])
def weekly_report(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    rows = attendance_service.get_weekly_report(db, auth.company_id, start, end)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/reports/monthly', tags=['Reports'])
def monthly_report(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    rows = attendance_service.get_monthly_report(db, auth.company_id, start, end)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/reports/overtime', tags=['Reports'])
def overtime_report(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    rows = attendance_service.get_overtime_report(db, auth.company_id, start, end)
    return ok([AttendanceEntryOut.model_validate(r) for r in rows])


@router.get('/reports/absence-analysis', tags=['Reports'])
def absence_report(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    return ok(attendance_service.get_absence_analysis(db, auth.company_id, start, end))


@router.get('/reports/branch-comparison', tags=['Reports'])
def branch_comparison(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    return ok(attendance_service.get_branch_comparison(db, auth.company_id, start, end))


@router.get('/reports/shift-variance', tags=['Reports'])
def shift_variance(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    return ok(attendance_service.get_shift_variance_report(db, auth.company_id, start, end))


@router.get('/reports/anomalies', tags=['Reports'])
def anomaly_report(from_date: str | None = Query(None, alias='from'), to_date: str | None = Query(None, alias='to'), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    start, end = parse_range(from_date, to_date)
    rows = attendance_service.get_anomaly_report(db, auth.company_id, start, end)
    only = [r for r in rows if r.flags]
    return ok([AttendanceEntryOut.model_validate(r) for r in only])


@router.post('/exports', tags=['Exports'])
def queue_export(payload: ExportJobIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_EXPORT))):
    row = attendance_service.queue_export_job(db, company_id=auth.company_id, requested_by_user_id=auth.user_id, format=payload.format, from_date=payload.from_date, to_date=payload.to_date, filters=payload.filters)
    return ok(ExportJobOut.model_validate(row))


@router.get('/exports', tags=['Exports'])
def list_export_jobs(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_EXPORT))):
    rows = db.query(AttendanceExportJob).filter(AttendanceExportJob.company_id == auth.company_id).order_by(AttendanceExportJob.created_at.desc()).all()
    return ok([ExportJobOut.model_validate(r) for r in rows])


@router.post('/exports/complete', tags=['Exports'])
def complete_export(payload: ExportCompleteIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_EXPORT))):
    row = attendance_service.complete_export_job(db, str(payload.job_id))
    return ok(ExportJobOut.model_validate(row))


@router.get('/audit-logs', tags=['Audit'])
def audit_logs(limit: int = 100, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_COMPANY))):
    rows = attendance_service.list_audit_logs(db, auth.company_id, limit)
    from app.schemas.common import AuditLogOut
    return ok([AuditLogOut.model_validate(r) for r in rows])


@router.get('/policy', tags=['Policy'])
def get_policy(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_CONFIGURE))):
    return ok(PolicyOut.model_validate(get_company_policy(db, auth.company_id)))


@router.put('/policy', tags=['Policy'])
def put_policy(payload: PolicyUpdateIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_CONFIGURE))):
    row = update_company_policy(db, auth.company_id, payload.model_dump(exclude_none=True))
    db.commit()
    db.refresh(row)
    return ok(PolicyOut.model_validate(row))


@router.get('/holidays', tags=['Policy'])
def get_holidays(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_VIEW_SELF))):
    return ok([HolidayOut.model_validate(r) for r in list_holidays(db, auth.company_id)])


@router.post('/holidays', tags=['Policy'])
def put_holiday(payload: HolidayIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_HOLIDAY_MANAGE))):
    row = upsert_holiday(db, auth.company_id, payload.model_dump())
    db.commit()
    db.refresh(row)
    return ok(HolidayOut.model_validate(row))


@router.put('/holidays/{holiday_id}', tags=['Policy'])
def patch_holiday(holiday_id: str, payload: HolidayIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_HOLIDAY_MANAGE))):
    try:
        row = update_holiday(db, auth.company_id, holiday_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return ok(HolidayOut.model_validate(row))


@router.delete('/holidays/{holiday_id}', tags=['Policy'])
def remove_holiday(holiday_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_HOLIDAY_MANAGE))):
    try:
        delete_holiday(db, auth.company_id, holiday_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return ok({'id': holiday_id, 'deleted': True})


@router.post('/holidays/import', tags=['Policy'])
def import_holidays(payload: HolidayImportIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_HOLIDAY_MANAGE))):
    try:
        rows = import_public_holidays(db, auth.company_id, payload.country_code, payload.state_code, payload.year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail='Holiday provider is unavailable') from exc
    db.commit()
    for row in rows:
        db.refresh(row)
    return ok([HolidayOut.model_validate(r) for r in rows], f'Imported {len(rows)} holidays')


@router.get('/geofences', tags=['Geofence'])
def list_geofences(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_GEOFENCE_MANAGE))):
    rows = db.query(GeofenceRule).filter(GeofenceRule.company_id == auth.company_id).all()
    return ok([GeofenceOut.model_validate(r) for r in rows])


@router.post('/geofences', tags=['Geofence'])
def create_geofence(payload: GeofenceIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_GEOFENCE_MANAGE))):
    row = GeofenceRule(company_id=auth.company_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(GeofenceOut.model_validate(row))


@router.put('/geofences/{geofence_id}', tags=['Geofence'])
def update_geofence(geofence_id: str, payload: GeofenceIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_GEOFENCE_MANAGE))):
    row = db.query(GeofenceRule).filter(GeofenceRule.company_id == auth.company_id, GeofenceRule.id == geofence_id).first()
    if not row:
        raise HTTPException(status_code=404, detail='Geofence not found')
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return ok(GeofenceOut.model_validate(row))


@router.delete('/geofences/{geofence_id}', tags=['Geofence'])
def delete_geofence(geofence_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_GEOFENCE_MANAGE))):
    row = db.query(GeofenceRule).filter(GeofenceRule.company_id == auth.company_id, GeofenceRule.id == geofence_id).first()
    if not row:
        raise HTTPException(status_code=404, detail='Geofence not found')
    db.delete(row)
    db.commit()
    return ok({'id': geofence_id, 'deleted': True})


@router.get('/shifts', tags=['Shifts'])
def list_shifts(user_id: str | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_SHIFT_MANAGE))):
    rows = attendance_service.list_shifts(db, auth.company_id, {'user_id': user_id} if user_id else {})
    return ok([ShiftOut.model_validate(r) for r in rows])


@router.post('/shifts', tags=['Shifts'])
def create_shift(payload: ShiftIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_SHIFT_MANAGE))):
    row = attendance_service.assign_shift(db, company_id=auth.company_id, actor_user_id=auth.user_id, payload=payload.model_dump())
    return ok(ShiftOut.model_validate(row))


@router.put('/shifts/{shift_id}', tags=['Shifts'])
def update_shift(shift_id: str, payload: ShiftIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_SHIFT_MANAGE))):
    row = attendance_service.update_shift(db, company_id=auth.company_id, shift_id=shift_id, actor_user_id=auth.user_id, payload=payload.model_dump())
    return ok(ShiftOut.model_validate(row))


@router.delete('/shifts/{shift_id}', tags=['Shifts'])
def delete_shift(shift_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_SHIFT_MANAGE))):
    return ok(attendance_service.delete_shift(db, company_id=auth.company_id, shift_id=shift_id, actor_user_id=auth.user_id))


@router.get('/kiosk/devices', tags=['Kiosk'])
def list_kiosks(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_KIOSK_MANAGE))):
    rows = attendance_service.list_kiosk_devices(db, auth.company_id)
    return ok([KioskDeviceOut.model_validate(r) for r in rows])


@router.post('/kiosk/devices', tags=['Kiosk'])
def create_kiosk(payload: KioskDeviceIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_KIOSK_MANAGE))):
    row = attendance_service.create_kiosk_device(db, company_id=auth.company_id, actor_user_id=auth.user_id, payload=payload.model_dump())
    return ok(KioskDeviceOut.model_validate(row))


@router.put('/kiosk/devices/{device_id}', tags=['Kiosk'])
def update_kiosk(device_id: str, payload: KioskDeviceIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_KIOSK_MANAGE))):
    row = attendance_service.update_kiosk_device(db, company_id=auth.company_id, device_id=device_id, actor_user_id=auth.user_id, payload=payload.model_dump())
    return ok(KioskDeviceOut.model_validate(row))


@router.delete('/kiosk/devices/{device_id}', tags=['Kiosk'])
def delete_kiosk(device_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_KIOSK_MANAGE))):
    return ok(attendance_service.delete_kiosk_device(db, company_id=auth.company_id, device_id=device_id, actor_user_id=auth.user_id))


@router.post('/kiosk/check-in', tags=['Kiosk'])
def kiosk_check_in(payload: KioskCheckInIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_CHECK_IN))):
    row = attendance_service.kiosk_check_in(db, company_id=auth.company_id, actor_user_id=auth.user_id, user_id=str(payload.user_id), employee_code=payload.employee_code, branch_id=str(payload.branch_id) if payload.branch_id else None, kiosk_device_id=str(payload.kiosk_device_id) if payload.kiosk_device_id else None, notes=payload.notes)
    return ok(AttendanceEntryOut.model_validate(row))


@router.post('/offline-sync', tags=['Offline Sync'])
def offline_sync(payload: OfflineSyncIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_CHECK_IN))):
    row = attendance_service.queue_offline_sync(db, company_id=auth.company_id, user_id=auth.user_id, source=payload.source, payload=payload.payload)
    return ok({'id': str(row.id), 'status': row.status})


@router.post('/offline-sync/process', tags=['Offline Sync'])
def process_offline(payload: dict, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_JOB_RUN))):
    row = attendance_service.process_offline_sync_event(db, str(payload.get('event_id') or payload.get('eventId')))
    return ok({'id': str(row.id), 'status': row.status, 'synced_at': row.synced_at.isoformat() if row.synced_at else None})


@router.get('/notifications', tags=['Notifications'])
def list_notifications(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_NOTIFICATION_MANAGE))):
    rows = db.query(NotificationEvent).filter(NotificationEvent.company_id == auth.company_id).order_by(NotificationEvent.created_at.desc()).all()
    return ok([NotificationEventOut.model_validate(r) for r in rows])


@router.post('/imports/entries/csv', tags=['Imports'])
def import_entries_csv(file: UploadFile = File(...), db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.ATTENDANCE_MANUAL_ENTRY))):
    content = file.file.read().decode('utf-8')
    reader = csv.DictReader(content.splitlines())
    created = []
    for row in reader:
        item = attendance_service.create_manual_entry(
            db,
            company_id=auth.company_id,
            user_id=row['user_id'],
            employee_code=row.get('employee_code') or None,
            source='manual',
            check_in_at=datetime.fromisoformat(row['check_in_at']),
            check_out_at=datetime.fromisoformat(row['check_out_at']),
            reason=row.get('reason') or 'Imported entry',
            branch_id=row.get('branch_id') or None,
            scheduled_start_at=datetime.fromisoformat(row['scheduled_start_at']) if row.get('scheduled_start_at') else None,
            scheduled_end_at=datetime.fromisoformat(row['scheduled_end_at']) if row.get('scheduled_end_at') else None,
            actor_user_id=auth.user_id,
            notes=row.get('notes') or None,
            break_minutes=int(row.get('break_minutes') or 0),
        )
        created.append(AttendanceEntryOut.model_validate(item))
    return ok(created, f'Imported {len(created)} attendance entries')


@router.get('/imports/entries/template', tags=['Imports'])
def import_template():
    csv_content = 'user_id,employee_code,branch_id,check_in_at,check_out_at,scheduled_start_at,scheduled_end_at,reason,notes\n'
    return StreamingResponse(BytesIO(csv_content.encode('utf-8')), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=attendance-import-template.csv'})
