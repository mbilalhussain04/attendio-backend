from datetime import date, datetime
import base64
import json
from fastapi import APIRouter, Depends, Query, Request
import httpx
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.scheduling import RosterTemplateRequest, ScheduleAssignmentRequest, ShiftTemplateRequest
from app.services.microsoft_graph import create_calendar_event, delete_calendar_event, list_calendar_view, update_calendar_event
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


def serialize_microsoft_event(event: dict, user):
    start = _event_dt(event.get('start'))
    end = _event_dt(event.get('end'))
    date_value = start.date().isoformat() if start else date.today().isoformat()
    start_time = start.strftime('%H:%M') if start else None
    end_time = end.strftime('%H:%M') if end else None
    subject = event.get('subject') or 'Microsoft calendar event'
    is_meeting = bool(event.get('isOnlineMeeting') or event.get('onlineMeeting'))
    return {
        'id': f"microsoft:{event.get('id')}",
        'external_id': event.get('id'),
        'external_provider': 'microsoft_teams',
        'employee_id': str(user.id),
        'employee_name': ' '.join(part for part in [user.first_name, user.last_name] if part),
        'employee_code': user.employee_code,
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
    db: Session = Depends(get_db),
    user=Depends(require_permissions('schedule.view_self', 'schedule.view_team', 'schedule.view_company', 'schedule.manage', 'settings.tenant', 'reports.company')),
):
    permissions = set(auth_service.permission_keys_for_user(db, user))
    if 'schedule.view_company' not in permissions and 'schedule.manage' not in permissions and 'settings.tenant' not in permissions and 'reports.company' not in permissions:
        if 'schedule.view_team' in permissions:
            allowed_ids = auth_service.direct_and_indirect_report_ids(db, actor=user)
            if employee_id and str(employee_id) not in allowed_ids:
                employee_id = str(user.id)
        else:
            employee_id = str(user.id)
    rows = scheduling_service.list_assignments(db, actor=user, date_from=date_from, date_to=date_to, employee_id=employee_id)
    data = [scheduling_service.serialize_assignment(assignment, shift, employee) for assignment, shift, employee in rows]
    meta = {'sources': {'manual': {'status': 'connected', 'count': len(data)}}}
    if not employee_id or str(employee_id) == str(user.id):
        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') == 'connected' and integration.get('scheduling_enabled') is False:
            meta['sources']['microsoft_teams'] = {
                'status': 'connected',
                'count': 0,
                'calendar_status': integration.get('calendar_status') or 'unavailable',
                'message': integration.get('calendar_unavailable_reason') or 'Microsoft calendar access is not enabled for this account.',
            }
        elif integration.get('scheduling_enabled') and integration.get('status') == 'connected':
            try:
                events, next_integration = list_calendar_view(integration, date_from=date_from, date_to=date_to)
                local_external_ids = {str(item.get('external_id')) for item in data if item.get('external_provider') == 'microsoft_teams' and item.get('external_id')}
                microsoft_rows = [
                    row
                    for event in events
                    for row in [serialize_microsoft_event(event, user)]
                    if str(event.get('id')) not in local_external_ids
                ]
                data.extend(microsoft_rows)
                meta['sources']['microsoft_teams'] = {'status': 'connected', 'count': len(microsoft_rows)}
                if next_integration != integration:
                    integrations['microsoft_teams'] = next_integration
                    metadata['integrations'] = integrations
                    user.company.metadata_json = metadata
                    db.add(user.company)
                    db.commit()
            except httpx.HTTPStatusError as exc:
                message = graph_error_message(exc)
                hint = graph_token_hint(integration)
                if exc.response.status_code == 401 and hint:
                    message = f'{message}. {hint}'
                meta['sources']['microsoft_teams'] = {'status': 'error', 'count': 0, 'status_code': exc.response.status_code, 'message': message}
            except httpx.HTTPError as exc:
                meta['sources']['microsoft_teams'] = {'status': 'error', 'count': 0, 'message': str(exc)}
        else:
            meta['sources']['microsoft_teams'] = {'status': integration.get('status') or 'disconnected', 'count': 0}
    return {'message': 'Schedule assignments fetched successfully', 'data': data, 'meta': meta}


@router.post('/assignments', tags=['Scheduling'])
def upsert_assignment(payload: ScheduleAssignmentRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    if payload.id and str(payload.id).startswith('microsoft:'):
        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') != 'connected':
            return {'message': 'Microsoft Teams is not connected', 'data': {'sync_error': 'Microsoft Teams is not connected'}}
        if not payload.start_time or not payload.end_time:
            return {'message': 'Microsoft event update requires start and end time', 'data': {'sync_error': 'Microsoft event update requires start and end time'}}
        event_id = str(payload.id).split(':', 1)[1]
        try:
            event, next_integration = update_calendar_event(
                integration,
                event_id=event_id,
                subject=payload.subject,
                work_date=payload.work_date,
                start_time=payload.start_time,
                end_time=payload.end_time,
                notes=payload.notes,
                location=payload.location,
            )
            if next_integration != integration:
                integrations['microsoft_teams'] = next_integration
                metadata['integrations'] = integrations
                user.company.metadata_json = metadata
                db.add(user.company)
                db.commit()
            row = serialize_microsoft_event({
                **event,
                'id': event.get('id') or event_id,
                'subject': event.get('subject') or payload.subject or 'Microsoft calendar event',
                'start': {'dateTime': f'{payload.work_date.isoformat()}T{payload.start_time.isoformat(timespec="minutes")}:00'},
                'end': {'dateTime': f'{payload.work_date.isoformat()}T{payload.end_time.isoformat(timespec="minutes")}:00'},
            }, user)
            return {'message': 'Microsoft event updated successfully', 'data': row}
        except httpx.HTTPStatusError as exc:
            return {'message': 'Microsoft event could not be updated', 'data': {'sync_error': graph_error_message(exc)}}
        except httpx.HTTPError as exc:
            return {'message': 'Microsoft event could not be updated', 'data': {'sync_error': str(exc)}}
    item, shift, employee, conflicts = scheduling_service.upsert_assignment(db, actor=user, payload=payload, request_meta=req_meta(request))
    data = {**scheduling_service.serialize_assignment(item, shift, employee), 'conflicts': conflicts}
    if payload.sync_provider == 'microsoft_teams':
        def cancel_unsynced_new_item():
            if payload.id:
                return
            item.status = 'cancelled'
            db.add(item)
            db.commit()

        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') != 'connected':
            data['sync_error'] = 'Microsoft Teams is not connected'
            cancel_unsynced_new_item()
        elif integration.get('scheduling_enabled') is False:
            data['sync_error'] = integration.get('calendar_unavailable_reason') or 'Microsoft calendar access is not enabled for this account'
            cancel_unsynced_new_item()
        else:
            try:
                existing_external_id = (item.metadata_json or {}).get('external_id')
                if existing_external_id:
                    event, next_integration = update_calendar_event(
                        integration,
                        event_id=str(existing_external_id),
                        subject=payload.subject or shift.name,
                        work_date=item.work_date,
                        start_time=shift.start_time,
                        end_time=shift.end_time,
                        notes=item.notes,
                        location=payload.location,
                    )
                    if not event:
                        event = {'id': existing_external_id, 'webLink': (item.metadata_json or {}).get('external_link')}
                else:
                    event, next_integration = create_calendar_event(
                        integration,
                        subject=payload.subject or shift.name,
                        work_date=item.work_date,
                        start_time=shift.start_time,
                        end_time=shift.end_time,
                        notes=item.notes,
                        location=payload.location,
                        attendee_emails=payload.attendee_emails,
                        create_online_meeting=payload.create_online_meeting,
                    )
                external_metadata = dict(item.metadata_json or {})
                external_metadata.update({
                    'external_provider': 'microsoft_teams',
                    'external_id': event.get('id') or existing_external_id,
                    'external_link': event.get('webLink') or external_metadata.get('external_link'),
                    'source': 'manual',
                })
                item.metadata_json = external_metadata
                db.add(item)
                db.commit()
                db.refresh(item)
                data = {**scheduling_service.serialize_assignment(item, shift, employee), 'conflicts': conflicts}
                if next_integration != integration:
                    integrations['microsoft_teams'] = next_integration
                    metadata['integrations'] = integrations
                    user.company.metadata_json = metadata
                    db.add(user.company)
                    db.commit()
            except httpx.HTTPStatusError as exc:
                data['sync_error'] = graph_error_message(exc)
                cancel_unsynced_new_item()
            except httpx.HTTPError as exc:
                data['sync_error'] = str(exc)
                cancel_unsynced_new_item()
    return {'message': 'Schedule assignment saved successfully', 'data': data}


@router.delete('/assignments/{assignment_id}', tags=['Scheduling'])
def delete_assignment(assignment_id: str, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('schedule.manage', 'settings.tenant'))):
    if str(assignment_id).startswith('microsoft:'):
        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') == 'connected':
            next_integration = delete_calendar_event(integration, event_id=str(assignment_id).split(':', 1)[1])
            if next_integration != integration:
                integrations['microsoft_teams'] = next_integration
                metadata['integrations'] = integrations
                user.company.metadata_json = metadata
                db.add(user.company)
                db.commit()
        return {'message': 'Microsoft event deleted', 'data': {'id': assignment_id, 'status': 'cancelled'}}
    item = scheduling_service.delete_assignment(db, actor=user, assignment_id=assignment_id, request_meta=req_meta(request))
    external_id = (item.metadata_json or {}).get('external_id')
    if external_id and (item.metadata_json or {}).get('external_provider') == 'microsoft_teams':
        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') == 'connected':
            next_integration = delete_calendar_event(integration, event_id=str(external_id))
            if next_integration != integration:
                integrations['microsoft_teams'] = next_integration
                metadata['integrations'] = integrations
                user.company.metadata_json = metadata
                db.add(user.company)
                db.commit()
    return {'message': 'Schedule assignment cancelled', 'data': scheduling_service.serialize_assignment(item)}
