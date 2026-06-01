import uuid
from datetime import datetime, time
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.models.scheduling import RosterTemplate, ScheduleAssignment, ShiftTemplate
from app.models.user import User
from app.services.audit import log_audit


def _to_uuid(value: str, label: str = 'id') -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        bad_request(f'Invalid {label}')
        raise exc


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _ranges(start: time, end: time):
    start_minute = _minutes(start)
    end_minute = _minutes(end)
    if end_minute > start_minute:
        return [(start_minute, end_minute)]
    return [(start_minute, 24 * 60), (0, end_minute)]


def _schedule_conflict(first: ShiftTemplate, second: ShiftTemplate) -> bool:
    same_template = str(first.id) == str(second.id)
    same_name = (first.name or '').strip().lower() == (second.name or '').strip().lower()
    same_timing = first.start_time == second.start_time and first.end_time == second.end_time
    return same_template or same_name or same_timing


def _code_prefix(name: str | None) -> str:
    words = [word for word in ''.join(char if char.isalnum() else ' ' for char in (name or '')).upper().split() if word]
    if not words:
        return 'SHFT'
    if len(words) == 1:
        return words[0][:4].ljust(4, 'X')
    return ''.join(word[0] for word in words)[:4].ljust(4, 'X')


class SchedulingService:
    def serialize_shift(self, item: ShiftTemplate):
        return {
            'id': str(item.id),
            'name': item.name,
            'code': item.code,
            'start_time': item.start_time.isoformat(timespec='minutes'),
            'end_time': item.end_time.isoformat(timespec='minutes'),
            'break_minutes': item.break_minutes,
            'timezone': item.timezone,
            'location_id': item.location_id,
            'department_id': item.department_id,
            'color': item.color,
            'status': item.status,
        }

    def serialize_roster(self, item: RosterTemplate):
        return {
            'id': str(item.id),
            'name': item.name,
            'shift_template_id': str(item.shift_template_id),
            'start_date': item.start_date.isoformat() if item.start_date else None,
            'end_date': item.end_date.isoformat() if item.end_date else None,
            'days_of_week': item.days_of_week or [],
            'employee_ids': item.employee_ids or [],
            'status': item.status,
        }

    def serialize_assignment(self, item: ScheduleAssignment, shift: ShiftTemplate | None = None, employee: User | None = None):
        metadata = item.metadata_json or {}
        return {
            'id': str(item.id),
            'employee_id': str(item.employee_id),
            'employee_name': ' '.join(part for part in [getattr(employee, 'first_name', ''), getattr(employee, 'last_name', '')] if part) if employee else None,
            'employee_code': getattr(employee, 'employee_code', None) if employee else None,
            'shift_template_id': str(item.shift_template_id),
            'shift_name': shift.name if shift else None,
            'shift_code': shift.code if shift else None,
            'shift_color': shift.color if shift else None,
            'break_minutes': shift.break_minutes if shift else None,
            'start_time': shift.start_time.isoformat(timespec='minutes') if shift else None,
            'end_time': shift.end_time.isoformat(timespec='minutes') if shift else None,
            'work_date': item.work_date.isoformat(),
            'status': item.status,
            'notes': item.notes,
            'location': metadata.get('location'),
            'attendee_emails': metadata.get('attendee_emails') or [],
            'repeat_rule': metadata.get('repeat_rule'),
            'external_provider': metadata.get('external_provider'),
            'external_id': metadata.get('external_id'),
            'external_link': metadata.get('external_link'),
            'source': metadata.get('source') or 'manual',
            'created_at': item.created_at,
            'updated_at': item.updated_at,
        }

    def list_shifts(self, db: Session, *, actor: User, status: str | None = None):
        stmt = select(ShiftTemplate).where(ShiftTemplate.company_id == actor.company_id).order_by(ShiftTemplate.name.asc())
        if status:
            stmt = stmt.where(ShiftTemplate.status == status)
        return db.execute(stmt).scalars().all()

    def upsert_shift(self, db: Session, *, actor: User, payload, request_meta: dict):
        item = None
        if payload.id:
            item = db.get(ShiftTemplate, _to_uuid(payload.id))
            if not item or item.company_id != actor.company_id:
                not_found('Shift template not found')
        if not item:
            item = ShiftTemplate(company_id=actor.company_id)
        data = payload.model_dump(exclude={'id'})
        if not data.get('code'):
            prefix = _code_prefix(data.get('name'))
            existing_codes = set(db.execute(select(ShiftTemplate.code).where(ShiftTemplate.company_id == actor.company_id, ShiftTemplate.id != getattr(item, 'id', None))).scalars().all())
            code = prefix
            counter = 1
            while code in existing_codes:
                counter += 1
                code = f'{prefix[:4]}{counter:02d}'
            data['code'] = code[:6]
        else:
            data['code'] = str(data['code']).upper()[:6]
        for key, value in data.items():
            setattr(item, key, value)
        item.updated_at = datetime.utcnow()
        db.add(item)
        db.commit()
        db.refresh(item)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='schedule.shift_saved', entity_type='shift_template', entity_id=item.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'name': item.name})
        return item

    def delete_shift(self, db: Session, *, actor: User, shift_id: str, request_meta: dict):
        item = db.get(ShiftTemplate, _to_uuid(shift_id))
        if not item or item.company_id != actor.company_id:
            not_found('Shift template not found')
        item.status = 'inactive'
        db.add(item)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='schedule.shift_inactivated', entity_type='shift_template', entity_id=item.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})
        return item

    def list_rosters(self, db: Session, *, actor: User):
        return db.execute(select(RosterTemplate).where(RosterTemplate.company_id == actor.company_id).order_by(RosterTemplate.name.asc())).scalars().all()

    def upsert_roster(self, db: Session, *, actor: User, payload, request_meta: dict):
        shift = db.get(ShiftTemplate, _to_uuid(payload.shift_template_id, 'shift_template_id'))
        if not shift or shift.company_id != actor.company_id:
            not_found('Shift template not found')
        item = None
        if payload.id:
            item = db.get(RosterTemplate, _to_uuid(payload.id))
            if not item or item.company_id != actor.company_id:
                not_found('Roster template not found')
        if not item:
            item = RosterTemplate(company_id=actor.company_id)
        data = payload.model_dump(exclude={'id'})
        data['shift_template_id'] = shift.id
        for key, value in data.items():
            setattr(item, key, value)
        db.add(item)
        db.commit()
        db.refresh(item)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='schedule.roster_saved', entity_type='roster_template', entity_id=item.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'name': item.name})
        return item

    def list_assignments(self, db: Session, *, actor: User, date_from=None, date_to=None, employee_id: str | None = None):
        stmt = select(ScheduleAssignment, ShiftTemplate, User).join(ShiftTemplate, ShiftTemplate.id == ScheduleAssignment.shift_template_id).join(User, User.id == ScheduleAssignment.employee_id).where(ScheduleAssignment.company_id == actor.company_id)
        if date_from:
            stmt = stmt.where(ScheduleAssignment.work_date >= date_from)
        if date_to:
            stmt = stmt.where(ScheduleAssignment.work_date <= date_to)
        if employee_id:
            stmt = stmt.where(ScheduleAssignment.employee_id == _to_uuid(employee_id, 'employee_id'))
        stmt = stmt.where(ScheduleAssignment.status != 'cancelled')
        stmt = stmt.order_by(ScheduleAssignment.work_date.asc(), ShiftTemplate.start_time.asc())
        return db.execute(stmt).all()

    def upsert_assignment(self, db: Session, *, actor: User, payload, request_meta: dict):
        employee = db.get(User, _to_uuid(payload.employee_id, 'employee_id'))
        if not employee or employee.company_id != actor.company_id or employee.status == 'deleted':
            not_found('Employee not found')
        shift = db.get(ShiftTemplate, _to_uuid(payload.shift_template_id, 'shift_template_id'))
        if not shift or shift.company_id != actor.company_id or shift.status != 'active':
            not_found('Active shift template not found')
        item = None
        if payload.id:
            item = db.get(ScheduleAssignment, _to_uuid(payload.id))
            if not item or item.company_id != actor.company_id:
                not_found('Schedule assignment not found')
        conflicts = []
        existing_rows = self.list_assignments(db, actor=actor, date_from=payload.work_date, date_to=payload.work_date, employee_id=str(employee.id))
        for assignment, existing_shift, _ in existing_rows:
            if payload.id and str(assignment.id) == str(payload.id):
                continue
            if assignment.status != 'cancelled' and _schedule_conflict(shift, existing_shift):
                conflicts.append(self.serialize_assignment(assignment, existing_shift, employee))
        if conflicts and not payload.force:
            bad_request('Schedule conflict detected')
        if not item:
            item = ScheduleAssignment(company_id=actor.company_id)
        item.employee_id = employee.id
        item.shift_template_id = shift.id
        item.work_date = payload.work_date
        item.status = payload.status
        item.notes = payload.notes
        metadata = dict(item.metadata_json or {})
        for key in ('location', 'attendee_emails', 'repeat_rule'):
            value = getattr(payload, key, None)
            if value:
                metadata[key] = value
            else:
                metadata.pop(key, None)
        item.metadata_json = metadata
        db.add(item)
        db.commit()
        db.refresh(item)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='schedule.assignment_saved', entity_type='schedule_assignment', entity_id=item.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'employee_id': str(employee.id), 'work_date': item.work_date.isoformat()})
        return item, shift, employee, conflicts

    def delete_assignment(self, db: Session, *, actor: User, assignment_id: str, request_meta: dict):
        item = db.get(ScheduleAssignment, _to_uuid(assignment_id))
        if not item or item.company_id != actor.company_id:
            not_found('Schedule assignment not found')
        item.status = 'cancelled'
        item.updated_at = datetime.utcnow()
        db.add(item)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='schedule.assignment_cancelled', entity_type='schedule_assignment', entity_id=item.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})
        return item


scheduling_service = SchedulingService()
