from datetime import date, datetime, time, timedelta, timezone

import httpx

from app.core.config import settings
from app.services.sso import microsoft_authority


GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0'
GRAPH_SCOPES = 'openid email profile offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Calendars.ReadWrite'
DEFAULT_TIMEZONE = 'Europe/Berlin'


def _expired(expires_at) -> bool:
    if not expires_at:
        return False
    try:
        return float(expires_at) <= datetime.now(timezone.utc).timestamp() + 60
    except (TypeError, ValueError):
        return False


def refresh_microsoft_token(integration: dict) -> dict:
    refresh_token = integration.get('refresh_token')
    if not refresh_token or not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_CLIENT_SECRET:
        return integration
    response = httpx.post(
        f'https://login.microsoftonline.com/{microsoft_authority()}/oauth2/v2.0/token',
        data={
            'client_id': settings.MICROSOFT_CLIENT_ID,
            'client_secret': settings.MICROSOFT_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'scope': GRAPH_SCOPES,
        },
        timeout=15,
    )
    response.raise_for_status()
    token = response.json()
    next_integration = dict(integration)
    next_integration.update({
        'access_token': token.get('access_token') or integration.get('access_token'),
        'refresh_token': token.get('refresh_token') or integration.get('refresh_token'),
        'expires_at': token.get('expires_at') or (datetime.now(timezone.utc).timestamp() + int(token.get('expires_in') or 0)),
        'scope': token.get('scope') or integration.get('scope'),
        'token_type': token.get('token_type') or integration.get('token_type'),
    })
    return next_integration


def _authorization_headers(integration: dict) -> dict:
    return {
        'Authorization': f"Bearer {integration['access_token']}",
        'Prefer': f'outlook.timezone="{DEFAULT_TIMEZONE}"',
    }


def _refresh_after_unauthorized(integration: dict, response: httpx.Response) -> dict:
    if response.status_code != 401 or not integration.get('refresh_token'):
        response.raise_for_status()
        return integration
    next_integration = refresh_microsoft_token(integration)
    if next_integration == integration:
        response.raise_for_status()
    return next_integration


def _calendar_view_params(start: str, end: str) -> dict:
    return {
        'startDateTime': f'{start}T00:00:00',
        'endDateTime': f'{end}T23:59:59',
        '$select': 'id,subject,start,end,isOnlineMeeting,onlineMeeting,webLink,showAs,categories,bodyPreview,location,attendees',
        '$orderby': 'start/dateTime',
        '$top': '100',
    }


def _events_params(start: str, end: str) -> dict:
    return {
        '$select': 'id,subject,start,end,isOnlineMeeting,onlineMeeting,webLink,showAs,categories,bodyPreview,location,attendees',
        '$filter': f"start/dateTime ge '{start}T00:00:00' and start/dateTime le '{end}T23:59:59'",
        '$orderby': 'start/dateTime',
        '$top': '100',
    }


def _get_calendar_view(integration: dict, start: str, end: str) -> httpx.Response:
    return httpx.get(
        f'{GRAPH_BASE_URL}/me/calendarView',
        headers=_authorization_headers(integration),
        params=_calendar_view_params(start, end),
        timeout=15,
    )


def _get_events(integration: dict, start: str, end: str) -> httpx.Response:
    return httpx.get(
        f'{GRAPH_BASE_URL}/me/events',
        headers=_authorization_headers(integration),
        params=_events_params(start, end),
        timeout=15,
    )


def list_calendar_view(integration: dict, *, date_from: date | None, date_to: date | None) -> tuple[list[dict], dict]:
    if not integration or integration.get('status') != 'connected' or not integration.get('access_token'):
        return [], integration
    next_integration = refresh_microsoft_token(integration) if _expired(integration.get('expires_at')) else integration
    start = (date_from or date.today()).isoformat()
    end = (date_to or date_from or date.today()).isoformat()
    response = _get_calendar_view(next_integration, start, end)
    if response.status_code == 401:
        next_integration = _refresh_after_unauthorized(next_integration, response)
        response = _get_calendar_view(next_integration, start, end)
    if response.status_code == 401:
        response = _get_events(next_integration, start, end)
    response.raise_for_status()
    return response.json().get('value') or [], next_integration


def _event_datetime(work_date: date, value: time, *, rolls_to_next_day: bool = False) -> str:
    event_date = work_date + timedelta(days=1 if rolls_to_next_day else 0)
    return datetime.combine(event_date, value).replace(second=0, microsecond=0).isoformat()


def create_calendar_event(
    integration: dict,
    *,
    subject: str,
    work_date: date,
    start_time: time,
    end_time: time,
    notes: str | None = None,
    location: str | None = None,
    attendee_emails: list[str] | None = None,
    create_online_meeting: bool = True,
) -> tuple[dict, dict]:
    if not integration or integration.get('status') != 'connected' or not integration.get('access_token'):
        return {}, integration
    next_integration = refresh_microsoft_token(integration) if _expired(integration.get('expires_at')) else integration
    ends_next_day = end_time <= start_time
    payload = {
        'subject': subject,
        'body': {'contentType': 'HTML', 'content': notes or ''},
        'start': {'dateTime': _event_datetime(work_date, start_time), 'timeZone': DEFAULT_TIMEZONE},
        'end': {'dateTime': _event_datetime(work_date, end_time, rolls_to_next_day=ends_next_day), 'timeZone': DEFAULT_TIMEZONE},
        'categories': ['Attendio'],
    }
    if location:
        payload['location'] = {'displayName': location}
    if attendee_emails:
        payload['attendees'] = [
            {'emailAddress': {'address': email, 'name': email}, 'type': 'required'}
            for email in attendee_emails
            if email
        ]
    if create_online_meeting:
        payload.update({'isOnlineMeeting': True, 'onlineMeetingProvider': 'teamsForBusiness'})

    response = httpx.post(
        f'{GRAPH_BASE_URL}/me/events',
        headers={**_authorization_headers(next_integration), 'Content-Type': 'application/json'},
        json=payload,
        timeout=15,
    )
    if response.status_code == 401:
        next_integration = _refresh_after_unauthorized(next_integration, response)
        response = httpx.post(
            f'{GRAPH_BASE_URL}/me/events',
            headers={**_authorization_headers(next_integration), 'Content-Type': 'application/json'},
            json=payload,
            timeout=15,
        )
    response.raise_for_status()
    return response.json(), next_integration


def update_calendar_event(
    integration: dict,
    *,
    event_id: str,
    subject: str | None = None,
    work_date: date,
    start_time: time,
    end_time: time,
    notes: str | None = None,
    location: str | None = None,
) -> tuple[dict, dict]:
    if not integration or integration.get('status') != 'connected' or not integration.get('access_token'):
        return {}, integration
    next_integration = refresh_microsoft_token(integration) if _expired(integration.get('expires_at')) else integration
    ends_next_day = end_time <= start_time
    payload = {
        'start': {'dateTime': _event_datetime(work_date, start_time), 'timeZone': DEFAULT_TIMEZONE},
        'end': {'dateTime': _event_datetime(work_date, end_time, rolls_to_next_day=ends_next_day), 'timeZone': DEFAULT_TIMEZONE},
    }
    if subject:
        payload['subject'] = subject
    if notes is not None:
        payload['body'] = {'contentType': 'HTML', 'content': notes}
    if location is not None:
        payload['location'] = {'displayName': location}
    response = httpx.patch(
        f'{GRAPH_BASE_URL}/me/events/{event_id}',
        headers={**_authorization_headers(next_integration), 'Content-Type': 'application/json'},
        json=payload,
        timeout=15,
    )
    if response.status_code == 401:
        next_integration = _refresh_after_unauthorized(next_integration, response)
        response = httpx.patch(
            f'{GRAPH_BASE_URL}/me/events/{event_id}',
            headers={**_authorization_headers(next_integration), 'Content-Type': 'application/json'},
            json=payload,
            timeout=15,
        )
    response.raise_for_status()
    return response.json() if response.content else {}, next_integration


def delete_calendar_event(integration: dict, *, event_id: str) -> dict:
    if not integration or integration.get('status') != 'connected' or not integration.get('access_token'):
        return integration
    next_integration = refresh_microsoft_token(integration) if _expired(integration.get('expires_at')) else integration
    response = httpx.delete(
        f'{GRAPH_BASE_URL}/me/events/{event_id}',
        headers=_authorization_headers(next_integration),
        timeout=15,
    )
    if response.status_code == 401:
        next_integration = _refresh_after_unauthorized(next_integration, response)
        response = httpx.delete(
            f'{GRAPH_BASE_URL}/me/events/{event_id}',
            headers=_authorization_headers(next_integration),
            timeout=15,
        )
    if response.status_code != 404:
        response.raise_for_status()
    return next_integration
