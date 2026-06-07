from datetime import date, datetime
import base64
import json
from fastapi import APIRouter, Depends, Query, Request
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request
from app.db.session import get_db
from app.deps.auth import require_permissions
from app.models.user import User
from app.schemas.scheduling import RosterTemplateRequest, ScheduleAssignmentRequest, ShiftTemplateRequest
from app.services.auth import service as auth_service
from app.services.scheduling import scheduling_service

router = APIRouter(prefix='/scheduling')


def req_meta(request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


def _event_dt(value: dict | None):
    raw = (value or {}).get('dateTime')
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None


def serialize_microsoft_event(event: dict, user, owner_user=None, owner_email: str | None = None):
    start = _event_dt(event.get('start'))
    end = _event_dt(event.get('end'))
    date_value = start.date().isoformat() if start else date.today().isoformat()
    start_time = start.strftime('%H:%M') if start else None
    end_time = end.strftime('%H:%M') if end else None
    subject = event.get('subject') or 'Microsoft calendar event'
    is_meeting = bool(event.get('isOnlineMeeting') or event.get('onlineMeeting'))
    owner = owner_user
    resolved_owner_email = owner_email or getattr(owner, 'email', None)
    owner_name = ' '.join(part for part in [getattr(owner, 'first_name', ''), getattr(owner, 'last_name', '')] if part) or resolved_owner_email or 'Microsoft calendar'
    return {
        'id': f"microsoft:{event.get('id')}",
        'external_id': event.get('id'),
        'external_provider': 'microsoft_teams',
        'employee_id': None,
        'employee_name': None,
        'employee_code': None,
        'employee_email': None,
        'calendar_owner_id': str(owner.id) if owner else None,
        'calendar_owner_name': owner_name,
        'calendar_owner_email': resolved_owner_email,
        'entry_kind': 'meeting',
        'shift_template_id': f"microsoft:{event.get('id')}",
        'shift_name': subject,
        'shift_code': 'MS',
        'shift_color': '#2563eb' if is_meeting else '#14b8a6',
        'break_minutes': 0,
        'start_time': start_time,
        'end_time': end_time,
        'work_date': date_value,
        'status': 'published',
        'notes': event.get('webLink') or '',
        'location': ((event.get('location') or {}).get('displayName') or ''),
        'attendee_emails': [
            ((attendee.get('emailAddress') or {}).get('address'))
            for attendee in (event.get('attendees') or [])
            if (attendee.get('emailAddress') or {}).get('address')
        ],
        'source': 'microsoft_graph',
        'readonly': False,
    }


def microsoft_calendar_owner(db: Session, user, integration: dict):
    owner_email = (integration.get('connected_by') or integration.get('user_email') or '').strip().lower()
    owner = None
    if owner_email:
        owner = db.scalar(
            select(User).where(
                User.company_id == user.company_id,
                func.lower(User.email) == owner_email,
                User.status != 'deleted',
            )
        )
    return owner, owner_email or None


def graph_error_message(exc: httpx.HTTPStatusError) -> str:
    authenticate = exc.response.headers.get('www-authenticate')
    try:
        payload = exc.response.json()
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict) and payload.get('error_description'):
        message = payload.get('error_description')
        return f'{message}. {authenticate}' if authenticate else message
    if isinstance(payload, dict) and payload.get('error'):
        message = str(payload.get('error'))
        return f'{message}. {authenticate}' if authenticate else message
    error = payload.get('error') if isinstance(payload, dict) else {}
    code = error.get('code') if isinstance(error, dict) else None
    message = error.get('message') if isinstance(error, dict) else None
    if code or message:
        detail = f'{code or exc.response.status_code}: {message or exc.response.reason_phrase}'
        return f'{detail}. {authenticate}' if authenticate else detail
    text = exc.response.text.strip()
    detail = text[:300] if text else f'HTTP {exc.response.status_code}: {exc.response.reason_phrase}'
    return f'{detail}. {authenticate}' if authenticate else detail


def graph_token_hint(integration: dict) -> str | None:
    token = integration.get('access_token')
    if not token or token.count('.') < 2:
        return None
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return None
    audience = claims.get('aud')
    scopes = set(str(claims.get('scp') or '').split())
    graph_audiences = {'https://graph.microsoft.com', 'https://graph.microsoft.com/', '00000003-0000-0000-c000-000000000000'}
    if audience and audience not in graph_audiences:
        return f'Microsoft returned a token for the wrong audience ({audience}). Reconnect Microsoft Teams and approve Microsoft Graph permissions.'
    if 'Calendars.ReadWrite' not in scopes and 'Calendars.Read' not in scopes:
        return 'Microsoft token is missing calendar permission. In Azure add delegated Calendars.ReadWrite, then reconnect.'
    return None


def _valid_entry_kind(value: str | None) -> str | None:
    normalized = str(value or '').strip().lower()
    return normalized if normalized in {'shift', 'meeting'} else None


def _filter_entry_kind(rows: list[dict], entry_kind: str | None) -> list[dict]:
    kind = _valid_entry_kind(entry_kind)
    if not kind:
        return rows
    return [row for row in rows if row.get('entry_kind') == kind]


@router.get('/shifts', tags=['Scheduling'])
def list_shifts(status: str | None = Query(None), db: Session = Depends(get_db), user=Depends(require_permissions('schedule.view_self', 'schedule.view_team', 'schedule.view_company', 'schedule.manage', 'settings.tenant', 'reports.company'))):
    items = scheduling_service.list_shifts(db, actor=user, status=status)
    return {'message': 'Shift templates fetched successfully', 'data': [scheduling_service.serialize_shift(item) for item in items]}


@router.post('/shifts', tags=['Scheduling'])
def upsert_shift(payload: ShiftTemplateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    item = scheduling_service.upsert_shift(db, actor=user, payload=payload, request_meta=req_meta(request))
    return {'message': 'Shift template saved successfully', 'data': scheduling_service.serialize_shift(item)}


@router.delete('/shifts/{shift_id}', tags=['Scheduling'])
def delete_shift(shift_id: str, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    item = scheduling_service.delete_shift(db, actor=user, shift_id=shift_id, request_meta=req_meta(request))
    return {'message': 'Shift template inactivated', 'data': scheduling_service.serialize_shift(item)}


@router.get('/rosters', tags=['Scheduling'])
def list_rosters(db: Session = Depends(get_db), user=Depends(require_permissions('schedule.view_team', 'schedule.view_company', 'schedule.manage', 'settings.tenant', 'reports.company'))):
    items = scheduling_service.list_rosters(db, actor=user)
    return {'message': 'Roster templates fetched successfully', 'data': [scheduling_service.serialize_roster(item) for item in items]}


@router.post('/rosters', tags=['Scheduling'])
def upsert_roster(payload: RosterTemplateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    item = scheduling_service.upsert_roster(db, actor=user, payload=payload, request_meta=req_meta(request))
    return {'message': 'Roster template saved successfully', 'data': scheduling_service.serialize_roster(item)}


@router.get('/assignments', tags=['Scheduling'])
def list_assignments(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    employee_id: str | None = Query(None),
    entry_kind: str | None = Query(None),
    include_microsoft: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(require_permissions('schedule.view_self', 'schedule.view_team', 'schedule.view_company', 'schedule.manage', 'settings.tenant', 'reports.company')),
):
    requested_entry_kind = _valid_entry_kind(entry_kind)
    permissions = set(auth_service.permission_keys_for_user(db, user))
    company_schedule_access = any(permission in permissions for permission in ('schedule.view_company', 'schedule.manage', 'settings.tenant', 'reports.company'))
    permitted_employee_ids = None
    team_allowed_ids = set()
    if not company_schedule_access:
        allowed_ids = {str(user.id)}
        if 'schedule.view_team' in permissions:
            team_allowed_ids = set(map(str, auth_service.direct_and_indirect_report_ids(db, actor=user)))
            allowed_ids |= team_allowed_ids
            if employee_id and str(employee_id) not in allowed_ids:
                employee_id = str(user.id)
        else:
            employee_id = str(user.id)
        if not employee_id:
            permitted_employee_ids = allowed_ids
    rows = scheduling_service.list_assignments(db, actor=user, date_from=date_from, date_to=date_to, employee_id=employee_id, employee_ids=permitted_employee_ids)
    data = [scheduling_service.serialize_assignment(assignment, shift, employee) for assignment, shift, employee in rows]
    data = _filter_entry_kind(data, requested_entry_kind)
    meta = {'sources': {'manual': {'status': 'connected', 'count': len(data)}}}
    if include_microsoft:
        meta['sources']['microsoft_teams'] = {
            'status': 'ignored',
            'count': 0,
            'message': 'Microsoft calendar events are available from the Meetings API.',
        }
    return {'message': 'Schedule assignments fetched successfully', 'data': data, 'meta': meta}


@router.post('/assignments', tags=['Scheduling'])
def upsert_assignment(payload: ScheduleAssignmentRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    if request.url.path.endswith('/scheduling/assignments') and (payload.entry_kind == 'meeting' or payload.sync_provider == 'microsoft_teams'):
        bad_request('Meeting events must be saved through the Meetings API')
    if payload.id and str(payload.id).startswith('microsoft:'):
        bad_request('Microsoft calendar events must be saved through the Meetings API')
    item, shift, employee, conflicts = scheduling_service.upsert_assignment(db, actor=user, payload=payload, request_meta=req_meta(request))
    data = {**scheduling_service.serialize_assignment(item, shift, employee), 'conflicts': conflicts}
    return {'message': 'Schedule assignment saved successfully', 'data': data}


@router.delete('/assignments/{assignment_id}', tags=['Scheduling'])
def delete_assignment(assignment_id: str, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    if str(assignment_id).startswith('microsoft:'):
        bad_request('Microsoft calendar events must be deleted through the Meetings API')
    item = scheduling_service.delete_assignment(db, actor=user, assignment_id=assignment_id, request_meta=req_meta(request))
    return {'message': 'Schedule assignment cancelled', 'data': scheduling_service.serialize_assignment(item)}
