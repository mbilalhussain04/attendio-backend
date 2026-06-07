from datetime import date

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.routes.scheduling import (
    graph_error_message,
    microsoft_calendar_owner,
    req_meta,
    serialize_microsoft_event,
)
from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.scheduling import ScheduleAssignmentRequest
from app.services.auth import service as auth_service
from app.services.meetings import meetings_service
from app.services.microsoft_graph import create_calendar_event, delete_calendar_event, list_calendar_view, update_calendar_event

router = APIRouter(prefix='/meetings')


def _meeting_permissions(db: Session, user, employee_id: str | None):
    permissions = set(auth_service.permission_keys_for_user(db, user))
    company_access = any(permission in permissions for permission in (
        'meetings.view_company',
        'meetings.manage',
        'schedule.view_company',
        'schedule.manage',
        'settings.tenant',
        'reports.company',
    ))
    permitted_employee_ids = None
    if not company_access:
        allowed_ids = {str(user.id)}
        if 'meetings.view_team' in permissions or 'schedule.view_team' in permissions:
            allowed_ids |= set(map(str, auth_service.direct_and_indirect_report_ids(db, actor=user)))
            if employee_id and str(employee_id) not in allowed_ids:
                employee_id = str(user.id)
        else:
            employee_id = str(user.id)
        if not employee_id:
            permitted_employee_ids = allowed_ids
    return employee_id, permitted_employee_ids


@router.get('/assignments', tags=['Meetings'])
def list_meetings(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    employee_id: str | None = Query(None),
    include_microsoft: bool = Query(True),
    db: Session = Depends(get_db),
    user=Depends(require_permissions(
        'meetings.view_self',
        'meetings.view_team',
        'meetings.view_company',
        'meetings.manage',
        'schedule.view_self',
        'schedule.view_team',
        'schedule.view_company',
        'schedule.manage',
        'settings.tenant',
        'reports.company',
    )),
):
    employee_id, permitted_employee_ids = _meeting_permissions(db, user, employee_id)
    rows = meetings_service.list_events(db, actor=user, date_from=date_from, date_to=date_to, employee_id=employee_id, employee_ids=permitted_employee_ids)
    data = [meetings_service.serialize_event(event, employee) for event, employee in rows]
    meta = {'sources': {'manual': {'status': 'connected', 'count': len(data)}}}

    metadata = dict(user.company.metadata_json or {})
    integrations = dict(metadata.get('integrations') or {})
    integration = integrations.get('microsoft_teams') or {}
    if include_microsoft and (not employee_id or str(employee_id) == str(user.id)):
        if integration.get('status') == 'connected' and integration.get('scheduling_enabled') is False:
            meta['sources']['microsoft_teams'] = {
                'status': 'connected',
                'count': 0,
                'calendar_status': 'unavailable',
                'message': integration.get('calendar_unavailable_reason') or 'Microsoft calendar access is unavailable',
            }
        elif integration.get('status') == 'connected':
            try:
                owner, owner_email = microsoft_calendar_owner(db, user, integration)
                events, next_integration = list_calendar_view(integration, date_from=date_from, date_to=date_to)
                local_external_ids = {str(item.get('external_id')) for item in data if item.get('external_provider') == 'microsoft_teams' and item.get('external_id')}
                microsoft_rows = [
                    serialize_microsoft_event(event, user, owner_user=owner, owner_email=owner_email)
                    for event in events
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
                meta['sources']['microsoft_teams'] = {'status': 'error', 'count': 0, 'status_code': exc.response.status_code, 'message': graph_error_message(exc)}
            except httpx.HTTPError as exc:
                meta['sources']['microsoft_teams'] = {'status': 'error', 'count': 0, 'message': str(exc)}
        else:
            meta['sources']['microsoft_teams'] = {'status': integration.get('status') or 'disconnected', 'count': 0}
    return {'message': 'Meeting events fetched successfully', 'data': data, 'meta': meta}


@router.post('/assignments', tags=['Meetings'])
def upsert_meeting(
    payload: ScheduleAssignmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permissions('meetings.manage', 'schedule.manage', 'settings.tenant')),
):
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
            owner, owner_email = microsoft_calendar_owner(db, user, integration)
            row = serialize_microsoft_event({
                **event,
                'id': event.get('id') or event_id,
                'subject': event.get('subject') or payload.subject or 'Microsoft calendar event',
                'start': {'dateTime': f'{payload.work_date.isoformat()}T{payload.start_time.isoformat(timespec="minutes")}:00'},
                'end': {'dateTime': f'{payload.work_date.isoformat()}T{payload.end_time.isoformat(timespec="minutes")}:00'},
            }, user, owner_user=owner, owner_email=owner_email)
            return {'message': 'Microsoft event updated successfully', 'data': row}
        except httpx.HTTPStatusError as exc:
            return {'message': 'Microsoft event could not be updated', 'data': {'sync_error': graph_error_message(exc)}}
        except httpx.HTTPError as exc:
            return {'message': 'Microsoft event could not be updated', 'data': {'sync_error': str(exc)}}

    item, employee, conflicts = meetings_service.upsert_event(db, actor=user, payload=payload, request_meta=req_meta(request))
    data = {**meetings_service.serialize_event(item, employee), 'conflicts': conflicts}
    if payload.sync_provider == 'microsoft_teams':
        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') != 'connected':
            data['sync_error'] = 'Microsoft Teams is not connected'
        elif integration.get('scheduling_enabled') is False:
            data['sync_error'] = integration.get('calendar_unavailable_reason') or 'Microsoft calendar access is not enabled for this account'
        else:
            try:
                if item.external_id:
                    event, next_integration = update_calendar_event(
                        integration,
                        event_id=str(item.external_id),
                        subject=item.title,
                        work_date=item.work_date,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        notes=item.notes,
                        location=item.location,
                    )
                    if not event:
                        event = {'id': item.external_id, 'webLink': item.external_link}
                else:
                    event, next_integration = create_calendar_event(
                        integration,
                        subject=item.title,
                        work_date=item.work_date,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        notes=item.notes,
                        location=item.location,
                        attendee_emails=item.attendee_emails,
                        create_online_meeting=payload.create_online_meeting,
                    )
                item = meetings_service.update_external_metadata(db, item, event=event, provider='microsoft_teams', actor=user)
                data = {**meetings_service.serialize_event(item, employee), 'conflicts': conflicts}
                if next_integration != integration:
                    integrations['microsoft_teams'] = next_integration
                    metadata['integrations'] = integrations
                    user.company.metadata_json = metadata
                    db.add(user.company)
                    db.commit()
            except httpx.HTTPStatusError as exc:
                data['sync_error'] = graph_error_message(exc)
            except httpx.HTTPError as exc:
                data['sync_error'] = str(exc)
    return {'message': 'Meeting event saved successfully', 'data': data}


@router.delete('/assignments/{assignment_id}', tags=['Meetings'])
def delete_meeting(
    assignment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_permissions('meetings.manage', 'schedule.manage', 'settings.tenant')),
):
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
    item = meetings_service.delete_event(db, actor=user, event_id=assignment_id, request_meta=req_meta(request))
    if item.external_provider == 'microsoft_teams' and item.external_id:
        metadata = dict(user.company.metadata_json or {})
        integrations = dict(metadata.get('integrations') or {})
        integration = integrations.get('microsoft_teams') or {}
        if integration.get('status') == 'connected':
            next_integration = delete_calendar_event(integration, event_id=str(item.external_id))
            if next_integration != integration:
                integrations['microsoft_teams'] = next_integration
                metadata['integrations'] = integrations
                user.company.metadata_json = metadata
                db.add(user.company)
                db.commit()
    return {'message': 'Meeting event cancelled', 'data': meetings_service.serialize_event(item)}
