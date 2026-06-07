import uuid
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.models.scheduling import MeetingEvent
from app.models.user import User
from app.schemas.scheduling import ScheduleAssignmentRequest
from app.services.audit import log_audit


def _to_uuid(value: str, field: str = 'id') -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        bad_request(f'Invalid {field}')


def _meeting_conflict(left: MeetingEvent, *, start_time: time, end_time: time) -> bool:
    left_start = left.start_time
    left_end = left.end_time
    return start_time < left_end and end_time > left_start


class MeetingsService:
    def serialize_event(self, item: MeetingEvent, employee: User | None = None):
        employee_name = ' '.join(part for part in [getattr(employee, 'first_name', ''), getattr(employee, 'last_name', '')] if part) if employee else None
        owner_name = item.metadata_json.get('calendar_owner_name') if item.metadata_json else None
        owner_email = item.metadata_json.get('calendar_owner_email') if item.metadata_json else None
        return {
            'id': str(item.id),
            'employee_id': str(item.employee_id),
            'employee_name': employee_name,
            'employee_code': getattr(employee, 'employee_code', None) if employee else None,
            'employee_email': getattr(employee, 'email', None) if employee else None,
            'calendar_owner_id': str(item.employee_id),
            'calendar_owner_name': owner_name or employee_name,
            'calendar_owner_email': owner_email or (getattr(employee, 'email', None) if employee else None),
            'entry_kind': 'meeting',
            'shift_template_id': f'meeting:{item.id}',
            'shift_name': item.title,
            'shift_code': 'MTG',
            'shift_color': item.color,
            'break_minutes': 0,
            'start_time': item.start_time.isoformat(timespec='minutes'),
            'end_time': item.end_time.isoformat(timespec='minutes'),
            'work_date': item.work_date.isoformat(),
            'status': item.status,
            'notes': item.notes,
            'location': item.location,
            'attendee_emails': item.attendee_emails or [],
            'repeat_rule': item.repeat_rule,
            'external_provider': item.external_provider,
            'external_id': item.external_id,
            'external_link': item.external_link,
            'source': item.source,
            'readonly': False,
            'created_at': item.created_at,
            'updated_at': item.updated_at,
        }

    def list_events(
        self,
        db: Session,
        *,
        actor: User,
        date_from: date | None = None,
        date_to: date | None = None,
        employee_id: str | None = None,
        employee_ids: set[str] | None = None,
    ):
        stmt = select(MeetingEvent, User).join(User, User.id == MeetingEvent.employee_id).where(MeetingEvent.company_id == actor.company_id)
        if date_from:
            stmt = stmt.where(MeetingEvent.work_date >= date_from)
        if date_to:
            stmt = stmt.where(MeetingEvent.work_date <= date_to)
        if employee_id:
            stmt = stmt.where(MeetingEvent.employee_id == _to_uuid(employee_id, 'employee_id'))
        if employee_ids is not None:
            ids = [_to_uuid(item, 'employee_id') for item in employee_ids]
            if not ids:
                return []
            stmt = stmt.where(MeetingEvent.employee_id.in_(ids))
        stmt = stmt.where(MeetingEvent.status != 'cancelled')
        stmt = stmt.order_by(MeetingEvent.work_date.asc(), MeetingEvent.start_time.asc())
        return db.execute(stmt).all()

    def upsert_event(self, db: Session, *, actor: User, payload: ScheduleAssignmentRequest, request_meta: dict):
        if not payload.employee_id:
            bad_request('employee_id is required')
        if not payload.work_date:
            bad_request('work_date is required')
        if not payload.start_time or not payload.end_time:
            bad_request('Meeting start and end time are required')
        if payload.start_time == payload.end_time:
            bad_request('start_time and end_time cannot be the same')
        title = (payload.subject or '').strip()
        if not title:
            bad_request('Meeting title is required')
        employee = db.get(User, _to_uuid(payload.employee_id, 'employee_id'))
        if not employee or employee.company_id != actor.company_id or employee.status == 'deleted':
            not_found('Employee not found')

        item = None
        if payload.id and not str(payload.id).startswith('microsoft:'):
            item = db.get(MeetingEvent, _to_uuid(payload.id))
            if not item or item.company_id != actor.company_id:
                not_found('Meeting event not found')

        conflicts = []
        existing_rows = self.list_events(db, actor=actor, date_from=payload.work_date, date_to=payload.work_date, employee_id=str(employee.id))
        for existing, existing_employee in existing_rows:
            if item and str(existing.id) == str(item.id):
                continue
            if existing.status != 'cancelled' and _meeting_conflict(existing, start_time=payload.start_time, end_time=payload.end_time):
                conflicts.append(self.serialize_event(existing, existing_employee))
        if conflicts and not payload.force:
            bad_request('Meeting conflict detected')

        if not item:
            item = MeetingEvent(company_id=actor.company_id)
        item.employee_id = employee.id
        item.title = title
        item.work_date = payload.work_date
        item.start_time = payload.start_time
        item.end_time = payload.end_time
        item.color = (payload.color if hasattr(payload, 'color') else None) or (item.color or '#2563eb')
        item.status = payload.status
        item.notes = payload.notes
        item.location = payload.location
        item.attendee_emails = payload.attendee_emails or []
        item.repeat_rule = payload.repeat_rule if payload.repeat_rule and payload.repeat_rule != 'none' else None
        metadata = dict(item.metadata_json or {})
        metadata.update({
            'entry_kind': 'meeting',
            'calendar_owner_id': str(employee.id),
            'calendar_owner_name': ' '.join(part for part in [employee.first_name, employee.last_name] if part) or employee.email,
            'calendar_owner_email': employee.email,
        })
        item.metadata_json = metadata
        db.add(item)
        db.commit()
        db.refresh(item)
        log_audit(
            db,
            company_id=actor.company_id,
            actor_user_id=actor.id,
            action='meeting.event_saved',
            entity_type='meeting_event',
            entity_id=item.id,
            ip_address=request_meta.get('ip_address'),
            user_agent=request_meta.get('user_agent'),
            payload={'employee_id': str(employee.id), 'work_date': item.work_date.isoformat()},
        )
        return item, employee, conflicts

    def update_external_metadata(self, db: Session, item: MeetingEvent, *, event: dict, provider: str, actor: User):
        metadata = dict(item.metadata_json or {})
        metadata.update({
            'entry_kind': 'meeting',
            'external_provider': provider,
            'external_id': event.get('id') or item.external_id,
            'external_link': event.get('webLink') or item.external_link,
            'source': 'manual',
            'calendar_owner_id': str(actor.id),
            'calendar_owner_name': ' '.join(part for part in [actor.first_name, actor.last_name] if part) or actor.email,
            'calendar_owner_email': actor.email,
        })
        item.external_provider = provider
        item.external_id = event.get('id') or item.external_id
        item.external_link = event.get('webLink') or item.external_link
        item.source = 'manual'
        item.metadata_json = metadata
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def delete_event(self, db: Session, *, actor: User, event_id: str, request_meta: dict):
        item = db.get(MeetingEvent, _to_uuid(event_id))
        if not item or item.company_id != actor.company_id:
            not_found('Meeting event not found')
        item.status = 'cancelled'
        db.add(item)
        db.commit()
        db.refresh(item)
        log_audit(
            db,
            company_id=actor.company_id,
            actor_user_id=actor.id,
            action='meeting.event_cancelled',
            entity_type='meeting_event',
            entity_id=item.id,
            ip_address=request_meta.get('ip_address'),
            user_agent=request_meta.get('user_agent'),
            payload={},
        )
        return item


meetings_service = MeetingsService()
