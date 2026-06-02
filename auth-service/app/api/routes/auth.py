from datetime import date, datetime, timezone
import base64
import json
import secrets
from fastapi import APIRouter, Depends, Request, Response, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from authlib.integrations.base_client.errors import OAuthError
import httpx
from sqlalchemy.orm import Session
from urllib.parse import urlencode
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.security import token_hash
from app.db.session import get_db
from app.deps.auth import get_current_user, require_permissions
from app.models.user import User
from app.schemas.auth import (
    BootstrapCompanyRequest,
    LoginRequest,
    RefreshRequest,
    SsoDiscoverRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    VerifyTokenRequest,
    ResendVerificationTokenRequest,
    MfaVerifyRequest,
    MfaDisableRequest,
    MfaRecoveryCodesRegenerateRequest,
    RevokeSessionRequest,
    CreateApiKeyRequest,
    RevokeApiKeyRequest,
    ImpersonateRequest,
    ProfileUpdateRequest,
    SecurityPolicyUpdateRequest,
    MfaReminderRequest,
)
from app.services.auth import service
from app.services import mfa as mfa_service
from app.services.sso import get_provider_config, microsoft_authority
from authlib.integrations.starlette_client import OAuth

router = APIRouter(prefix='/auth')
MICROSOFT_GRAPH_SCOPE = 'openid email profile offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Calendars.ReadWrite'
MICROSOFT_AUTHORIZE_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
MICROSOFT_TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
oauth = OAuth()


def req_meta(request: Request):
    forwarded_for = request.headers.get('x-forwarded-for')
    ip_address = forwarded_for.split(',')[0].strip() if forwarded_for else (request.client.host if request.client else None)
    return {
        'ip_address': ip_address,
        'user_agent': request.headers.get('user-agent'),
        'geo_country': request.headers.get('cf-ipcountry') or request.headers.get('x-geo-country'),
        'geo_city': request.headers.get('x-geo-city'),
        'device_id': request.cookies.get('attendio_device_id') or str(uuid4()),
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, company, device_id: str | None = None):
    opts = {'httponly': True, 'samesite': 'lax', 'secure': settings.COOKIE_SECURE, 'path': '/'}
    if settings.COOKIE_DOMAIN:
        opts['domain'] = settings.COOKIE_DOMAIN
    response.set_cookie(settings.SESSION_COOKIE_NAME, access_token, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **opts)
    security_policy = (company.metadata_json or {}).get('security_policy') or {}
    ttl_days = security_policy.get('session_ttl_days', settings.REFRESH_TOKEN_EXPIRE_DAYS)
    response.set_cookie(settings.REFRESH_COOKIE_NAME, refresh_token, max_age=ttl_days * 24 * 3600, **opts)
    response.set_cookie('tenant_slug', company.slug, max_age=ttl_days * 24 * 3600, **opts)
    response.set_cookie('tenant_host', company.domain, max_age=ttl_days * 24 * 3600, **opts)
    if device_id:
        response.set_cookie('attendio_device_id', device_id, max_age=ttl_days * 24 * 3600, httponly=False, samesite='lax', secure=settings.COOKIE_SECURE, path='/')


def clear_auth_cookies(response: Response):
    opts = {'path': '/', 'secure': settings.COOKIE_SECURE, 'samesite': 'lax'}
    if settings.COOKIE_DOMAIN:
        opts['domain'] = settings.COOKIE_DOMAIN
    cookie_names = {
        settings.SESSION_COOKIE_NAME,
        settings.REFRESH_COOKIE_NAME,
        'attendio_session',
        'attendio_refresh',
        'access_token',
        'refresh_token',
        'session',
        'tenant_slug',
        'tenant_host',
    }
    for name in cookie_names:
        response.delete_cookie(name, **opts)


def frontend_url(path: str | None, params: dict | None = None) -> str:
    target = path or settings.FRONTEND_AFTER_LOGIN
    if target.startswith('/'):
        target = f'{settings.FRONTEND_BASE_URL.rstrip("/")}{target}'
    if params:
        separator = '&' if '?' in target else '?'
        target = f'{target}{separator}{urlencode(params)}'
    return target


def cleared_session_redirect(request: Request, url: str) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url=url)


def microsoft_token_diagnostics(token_value: str | None) -> dict:
    if not token_value or token_value.count('.') < 2:
        return {'has_access_token': bool(token_value), 'token_format': 'opaque'}
    try:
        payload = token_value.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return {'has_access_token': True, 'token_format': 'unreadable'}
    return {
        'has_access_token': True,
        'token_format': 'jwt',
        'aud': claims.get('aud'),
        'scp': claims.get('scp'),
        'roles': claims.get('roles'),
        'tid': claims.get('tid'),
        'iss': claims.get('iss'),
        'exp': claims.get('exp'),
        'upn': claims.get('upn') or claims.get('preferred_username'),
    }


def save_microsoft_integration(company, actor_email: str, token: dict):
    metadata = dict(company.metadata_json or {})
    integrations = dict(metadata.get('integrations') or {})
    diagnostics = microsoft_token_diagnostics(token.get('access_token'))
    calendar_error = token.get('calendar_probe_error')
    calendar_unavailable_reason = None
    if calendar_error:
        scopes = set(str(diagnostics.get('scp') or '').split())
        if 'Calendars.ReadWrite' not in scopes and 'Calendars.Read' not in scopes:
            calendar_unavailable_reason = 'Microsoft token does not include calendar permission. Reconnect after granting Calendars.ReadWrite.'
        else:
            calendar_unavailable_reason = 'Microsoft calendar endpoints are not available for this account. Check Exchange Online mailbox/license or tenant calendar access policy.'

    integrations['microsoft_teams'] = {
        **(integrations.get('microsoft_teams') or {}),
        'provider': 'microsoft_teams',
        'name': 'Microsoft Teams',
        'status': 'connected',
        'connected_at': datetime.now(timezone.utc).isoformat(),
        'connected_by': actor_email,
        'scheduling_enabled': not bool(token.get('calendar_probe_error')),
        'source': 'microsoft_graph',
        'calendar_status': 'unavailable' if calendar_error else 'connected',
        'calendar_unavailable_reason': calendar_unavailable_reason,
        'last_error': token.get('calendar_probe_error'),
        'last_error_at': datetime.now(timezone.utc).isoformat() if token.get('calendar_probe_error') else None,
        'scope': token.get('scope'),
        'token_type': token.get('token_type'),
        'expires_at': token.get('expires_at'),
        'access_token': token.get('access_token'),
        'refresh_token': token.get('refresh_token'),
        'diagnostics': diagnostics,
    }
    metadata['integrations'] = integrations
    company.metadata_json = metadata
    return integrations['microsoft_teams']


def microsoft_error_from_response(response: httpx.Response) -> str:
    authenticate = response.headers.get('www-authenticate')
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    parts = [f'HTTP {response.status_code}']
    if isinstance(payload, dict):
        error = payload.get('error')
        if isinstance(error, dict):
            parts.append(str(error.get('code') or 'GraphError'))
            if error.get('message'):
                parts.append(str(error.get('message')))
        elif error:
            parts.append(str(error))
        if payload.get('error_description'):
            parts.append(str(payload.get('error_description')))
    elif response.text:
        parts.append(response.text[:300])
    if authenticate:
        parts.append(authenticate)
    return ': '.join(part for part in parts if part)


async def exchange_microsoft_code(code: str, redirect_uri: str) -> dict:
    tenant = microsoft_authority()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            MICROSOFT_TOKEN_URL.format(tenant=tenant),
            data={
                'client_id': settings.MICROSOFT_CLIENT_ID,
                'client_secret': settings.MICROSOFT_CLIENT_SECRET,
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'scope': MICROSOFT_GRAPH_SCOPE,
            },
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=400, detail=microsoft_error_from_response(response))
        token = response.json()
        if token.get('expires_in') and not token.get('expires_at'):
            token['expires_at'] = datetime.now(timezone.utc).timestamp() + int(token.get('expires_in') or 0)

        me = await client.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': f"Bearer {token.get('access_token')}"},
            params={'$select': 'id,displayName,userPrincipalName,mail'},
        )
        if me.status_code >= 400:
            raise HTTPException(status_code=400, detail=f'Microsoft Graph identity probe failed: {microsoft_error_from_response(me)}')
        token['microsoft_profile'] = me.json()

        today = date.today().isoformat()
        probe = await client.get(
            'https://graph.microsoft.com/v1.0/me/calendarView',
            headers={'Authorization': f"Bearer {token.get('access_token')}", 'Prefer': 'outlook.timezone="Europe/Berlin"'},
            params={'startDateTime': f'{today}T00:00:00', 'endDateTime': f'{today}T23:59:59', '$top': '1'},
        )
        if probe.status_code >= 400:
            events_probe = await client.get(
                'https://graph.microsoft.com/v1.0/me/events',
                headers={'Authorization': f"Bearer {token.get('access_token')}", 'Prefer': 'outlook.timezone="Europe/Berlin"'},
                params={
                    '$select': 'id,subject,start,end',
                    '$filter': f"start/dateTime ge '{today}T00:00:00' and start/dateTime le '{today}T23:59:59'",
                    '$top': '1',
                },
            )
            if events_probe.status_code >= 400:
                token['calendar_probe_error'] = f'Microsoft Graph calendar probe failed: {microsoft_error_from_response(probe)}; events fallback failed: {microsoft_error_from_response(events_probe)}'
                token['calendar_probe_status'] = events_probe.status_code
            else:
                token['calendar_probe_status'] = events_probe.status_code
                token['calendar_probe_fallback'] = 'events'
        else:
            token['calendar_probe_status'] = probe.status_code
    return token


def oauth_error_message(provider: str, exc: OAuthError) -> str:
    label = 'Microsoft' if provider in {'microsoft', 'microsoft_teams'} else 'Google' if provider in {'google', 'google_meet'} else 'OAuth'
    detail = getattr(exc, 'description', None) or getattr(exc, 'error', None) or str(exc)
    return f'{label} sign-in could not be completed. {detail}' if detail else f'{label} sign-in could not be completed. Please try again.'


def integration_provider_config(provider: str):
    provider = provider.lower().strip()
    if provider == 'google_meet':
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=501, detail='Google OAuth is not configured')
        return {
            'oauth_name': 'integration_google_meet',
            'display_name': 'Google Meet',
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'server_metadata_url': 'https://accounts.google.com/.well-known/openid-configuration',
            'client_kwargs': {'scope': 'openid email profile https://www.googleapis.com/auth/calendar.events'},
        }
    if provider == 'microsoft_teams':
        if not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_CLIENT_SECRET:
            raise HTTPException(status_code=501, detail='Microsoft OAuth is not configured')
        return {
            'oauth_name': 'integration_microsoft_teams',
            'display_name': 'Microsoft Teams',
            'client_id': settings.MICROSOFT_CLIENT_ID,
            'client_secret': settings.MICROSOFT_CLIENT_SECRET,
            'server_metadata_url': f'https://login.microsoftonline.com/{microsoft_authority()}/v2.0/.well-known/openid-configuration',
            'client_kwargs': {'scope': MICROSOFT_GRAPH_SCOPE},
        }
    raise HTTPException(status_code=400, detail='Unsupported integration provider')


@router.get('/integrations/config-status', tags=['Integrations'])
def integration_config_status(user=Depends(require_permissions('settings.tenant', 'reports.company'))):
    metadata = user.company.metadata_json or {}
    integrations = metadata.get('integrations') or {}
    microsoft_integration = integrations.get('microsoft_teams') or {}
    return {
        'message': 'Integration configuration status',
        'data': {
            'microsoft_teams': {
                'configured': bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET),
                'has_client_id': bool(settings.MICROSOFT_CLIENT_ID),
                'has_client_secret': bool(settings.MICROSOFT_CLIENT_SECRET),
                'tenant_id': settings.MICROSOFT_TENANT_ID,
                'authority': microsoft_authority(),
                'sso_redirect_uri': settings.OAUTH_REDIRECT_URI,
                'integration_redirect_uri': None,
                'required_redirect_uris': [
                    settings.OAUTH_REDIRECT_URI,
                    'http://localhost:8090/api/v1/auth/integrations/callback',
                ],
                'required_delegated_permissions': ['openid', 'email', 'profile', 'offline_access', 'User.Read', 'Calendars.ReadWrite'],
                'connection_status': microsoft_integration.get('status') or 'disconnected',
                'connected_by': microsoft_integration.get('connected_by'),
                'scope': microsoft_integration.get('scope'),
                'calendar_status': microsoft_integration.get('calendar_status'),
                'calendar_unavailable_reason': microsoft_integration.get('calendar_unavailable_reason'),
                'last_error': microsoft_integration.get('last_error'),
                'diagnostics': microsoft_integration.get('diagnostics') or microsoft_token_diagnostics(microsoft_integration.get('access_token')),
            }
        },
    }


@router.post('/bootstrap-company', tags=['Authentication'])
def bootstrap_company(payload: BootstrapCompanyRequest, request: Request, db: Session = Depends(get_db)):
    company, user, delivery = service.bootstrap_company(db, payload, req_meta(request))
    return {
        'message': 'Company bootstrapped successfully. Verify your email before signing in.',
        'data': {
            'company': {'id': str(company.id), 'name': company.name, 'slug': company.slug, 'domain': company.domain},
            'user': {'id': str(user.id), 'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name, 'employee_code': user.employee_code},
            'email_verification': delivery,
            'notes': {
                'slug_is_auto_generated': True,
                'domain_is_auto_generated': True,
                'tenant_login_url': service.build_tenant_base_url(company),
            },
        },
    }


@router.post('/login', tags=['Authentication'])
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    tenant = getattr(request.state, 'tenant', None) or service.resolve_company_by_slug(db, slug=payload.tenant_slug)
    data = service.login(db, email=payload.email, password=payload.password, mfa_token=payload.mfa_token, tenant=tenant, request_meta=req_meta(request))
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'], data.get('device_id'))
    company_metadata = data['company'].metadata_json or {}
    return {
        'message': data['display_message'],
        'data': {
            'display_name': f"{data['user'].first_name} {data['user'].last_name}",
            'user': {'id': str(data['user'].id), 'email': data['user'].email, 'email_verified': data['user'].email_verified, 'first_name': data['user'].first_name, 'last_name': data['user'].last_name, 'employee_code': data['user'].employee_code, 'profile_picture': (data['user'].metadata_json or {}).get('profile_picture_url'), 'avatar_url': (data['user'].metadata_json or {}).get('profile_picture_url'), 'role_key': data['user'].roles[0].key if data['user'].roles else None, 'role_name': data['user'].roles[0].name if data['user'].roles else None, 'roles': [role.key for role in data['user'].roles]},
            'company': {'id': str(data['company'].id), 'name': data['company'].name, 'slug': data['company'].slug, 'domain': data['company'].domain, 'industry': company_metadata.get('industry'), 'company_size': company_metadata.get('company_size'), 'language': company_metadata.get('language'), 'operating_model': company_metadata.get('operating_model'), 'onboarding_completed': company_metadata.get('onboarding_completed'), 'enabled_modules': company_metadata.get('enabled_modules') or [], 'terminology': company_metadata.get('terminology') or {}, 'integrations': company_metadata.get('integrations') or {}},
            'permissions': service.permission_keys_for_user(db, data['user']),
            'tenant_base_url': data['tenant_base_url'],
            'redirect_url': data['redirect_url'],
            'tenant_isolation': 'enabled',
        },
    }


@router.post('/sso/discover', tags=['SSO'])
def discover_sso(payload: SsoDiscoverRequest, request: Request, db: Session = Depends(get_db)):
    tenant = getattr(request.state, 'tenant', None)
    data = service.discover_sso_provider(db, email=payload.email, tenant=tenant)
    return {
        'message': 'SSO provider discovered',
        'data': {
            'provider': data['provider'],
            'login_url': data['login_url'],
            'company': {'id': str(data['company'].id), 'name': data['company'].name, 'slug': data['company'].slug, 'domain': data['company'].domain},
        },
    }


@router.get('/integrations/{provider}/connect', tags=['Integrations'])
async def connect_integration(provider: str, request: Request, user=Depends(require_permissions('settings.tenant'))):
    try:
        config = integration_provider_config(provider)
    except HTTPException as exc:
        status = 'not_configured' if exc.status_code == 501 else 'error'
        return RedirectResponse(url=frontend_url('/settings', {'integration': provider, 'status': status}))
    request.session['integration_provider'] = provider
    request.session['integration_user_id'] = str(user.id)
    request.session['integration_company_id'] = str(user.company_id)
    if provider == 'microsoft_teams':
        state = secrets.token_urlsafe(24)
        request.session['integration_state'] = state
        redirect_uri = str(request.url_for('integration_callback'))
        tenant = microsoft_authority()
        authorize_url = f'{MICROSOFT_AUTHORIZE_URL.format(tenant=tenant)}?{urlencode({
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": MICROSOFT_GRAPH_SCOPE,
            "state": state,
            "prompt": "consent",
        })}'
        return RedirectResponse(url=authorize_url)
    client = oauth.create_client(config['oauth_name']) or oauth.register(
        name=config['oauth_name'],
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        server_metadata_url=config['server_metadata_url'],
        client_kwargs=config['client_kwargs'],
    )
    extra_params = {'prompt': 'consent', 'scope': config['client_kwargs']['scope']} if provider == 'microsoft_teams' else {'scope': config['client_kwargs']['scope']}
    return await client.authorize_redirect(request, str(request.url_for('integration_callback')), **extra_params)


@router.get('/integrations/callback', name='integration_callback', tags=['Integrations'])
async def integration_callback(request: Request, db: Session = Depends(get_db)):
    provider = request.session.pop('integration_provider', None)
    user_id = request.session.pop('integration_user_id', None)
    company_id = request.session.pop('integration_company_id', None)
    expected_state = request.session.pop('integration_state', None)
    if not provider or not user_id or not company_id:
        return cleared_session_redirect(request, frontend_url('/settings', {'integration': 'missing', 'status': 'error'}))
    if request.query_params.get('error'):
        reason = request.query_params.get('error_description') or request.query_params.get('error')
        return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'error', 'reason': reason}))
    config = integration_provider_config(provider)
    if provider == 'microsoft_teams':
        if expected_state and request.query_params.get('state') != expected_state:
            return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'error', 'reason': 'Microsoft OAuth state mismatch'}))
        actor = db.get(User, UUID(str(user_id)))
        if not actor or str(actor.company_id) != str(company_id):
            return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'error'}))
        try:
            token = await exchange_microsoft_code(request.query_params.get('code') or '', str(request.url_for('integration_callback')))
        except HTTPException as exc:
            metadata = dict(actor.company.metadata_json or {})
            integrations = dict(metadata.get('integrations') or {})
            integrations['microsoft_teams'] = {
                **(integrations.get('microsoft_teams') or {}),
                'provider': 'microsoft_teams',
                'name': 'Microsoft Teams',
                'status': 'error',
                'scheduling_enabled': False,
                'last_error': str(exc.detail),
                'last_error_at': datetime.now(timezone.utc).isoformat(),
            }
            metadata['integrations'] = integrations
            actor.company.metadata_json = metadata
            db.add(actor.company)
            db.commit()
            return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'error', 'reason': str(exc.detail)}))
        save_microsoft_integration(actor.company, actor.email, token)
        db.add(actor.company)
        db.commit()
        return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'connected'}))
    client = oauth.create_client(config['oauth_name']) or oauth.register(
        name=config['oauth_name'],
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        server_metadata_url=config['server_metadata_url'],
        client_kwargs=config['client_kwargs'],
    )
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'error', 'reason': oauth_error_message(provider, exc)}))
    actor = db.get(User, UUID(str(user_id)))
    if not actor or str(actor.company_id) != str(company_id):
        return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'error'}))
    metadata = dict(actor.company.metadata_json or {})
    if provider == 'microsoft_teams':
        save_microsoft_integration(actor.company, actor.email, token)
    else:
        integrations = dict(metadata.get('integrations') or {})
        integrations[provider] = {
            'provider': provider,
            'name': config['display_name'],
            'status': 'connected',
            'connected_at': datetime.now(timezone.utc).isoformat(),
            'connected_by': actor.email,
            'scheduling_enabled': True,
            'scope': token.get('scope'),
            'token_type': token.get('token_type'),
            'expires_at': token.get('expires_at'),
            'access_token': token.get('access_token'),
            'refresh_token': token.get('refresh_token'),
        }
        metadata['integrations'] = integrations
        actor.company.metadata_json = metadata
    db.add(actor.company)
    db.commit()
    return cleared_session_redirect(request, frontend_url('/settings', {'integration': provider, 'status': 'connected'}))


@router.post('/refresh', tags=['Authentication'])
def refresh(payload: RefreshRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    incoming = payload.refresh_token or request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not incoming:
        raise HTTPException(status_code=401, detail='Refresh token is required')
    data = service.refresh(db, refresh_token=incoming)
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'], data.get('device_id'))
    return {
        'message': 'Session refreshed',
        'data': {
            'company': {'id': str(data['company'].id), 'name': data['company'].name, 'slug': data['company'].slug, 'domain': data['company'].domain},
        },
    }


@router.post('/logout', tags=['Authentication'])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    service.logout(db, token)
    clear_auth_cookies(response)
    return {'message': 'Logged out successfully'}


@router.get('/me', tags=['Authentication'])
def me(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    permissions = service.permission_keys_for_user(db, user)
    roles = [role.key for role in user.roles]
    role_name = user.roles[0].name if user.roles else None
    metadata = user.metadata_json or {}
    token_payload = getattr(request.state, 'token_payload', {}) or {}
    profile_picture_url = metadata.get('profile_picture_url') or metadata.get('provider_avatar_url')
    company_metadata = user.company.metadata_json or {}
    return {'message': 'Current user fetched successfully', 'data': {'user': {'id': str(user.id), 'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email, 'email_verified': user.email_verified, 'employee_code': user.employee_code, 'phone': user.phone, 'country': metadata.get('country'), 'city': metadata.get('city'), 'language': metadata.get('language'), 'job_title': metadata.get('job_title'), 'role_key': roles[0] if roles else None, 'role_name': role_name, 'roles': roles, 'contract_type': metadata.get('contract_type'), 'employment_type': metadata.get('employment_type'), 'department': metadata.get('department'), 'office': metadata.get('office'), 'branch_id': metadata.get('branch_id'), 'branch_name': metadata.get('branch_name'), 'start_date': metadata.get('start_date'), 'employment_start_date': metadata.get('employment_start_date') or metadata.get('start_date'), 'hire_date': metadata.get('hire_date'), 'expected_hours_period': metadata.get('expected_hours_period') or ('monthly' if metadata.get('monthly_hours') else 'weekly'), 'expected_hours': metadata.get('expected_hours') or metadata.get('monthly_hours') or metadata.get('weekly_hours'), 'weekly_hours': metadata.get('weekly_hours'), 'monthly_hours': metadata.get('monthly_hours'), 'notification_preferences': metadata.get('notification_preferences') or {}, 'mfa_enabled': user.mfa_enabled, 'is_kiosk': bool(token_payload.get('kiosk')), 'profile_picture': profile_picture_url, 'avatar_url': profile_picture_url, 'created_at': user.created_at, 'updated_at': user.updated_at}, 'company': {'id': str(user.company.id), 'name': user.company.name, 'slug': user.company.slug, 'domain': user.company.domain, 'created_at': getattr(user.company, 'created_at', None), 'industry': company_metadata.get('industry'), 'company_size': company_metadata.get('company_size'), 'language': company_metadata.get('language'), 'operating_model': company_metadata.get('operating_model'), 'onboarding_completed': company_metadata.get('onboarding_completed'), 'enabled_modules': company_metadata.get('enabled_modules') or [], 'terminology': company_metadata.get('terminology') or {}, 'integrations': company_metadata.get('integrations') or {}}, 'security_policy': service.get_security_policy(actor=user), 'permissions': permissions}}


@router.patch('/profile', tags=['Authentication'])
def update_profile(payload: ProfileUpdateRequest, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    updated = service.update_profile(db, actor=user, payload=payload, request_meta=req_meta(request))
    metadata = updated.metadata_json or {}
    return {'message': 'Profile updated successfully', 'data': {'user': {'id': str(updated.id), 'first_name': updated.first_name, 'last_name': updated.last_name, 'email': updated.email, 'phone': updated.phone, 'country': metadata.get('country'), 'city': metadata.get('city'), 'language': metadata.get('language'), 'notification_preferences': metadata.get('notification_preferences') or {}, 'mfa_enabled': updated.mfa_enabled, 'profile_picture': metadata.get('profile_picture_url'), 'avatar_url': metadata.get('profile_picture_url'), 'updated_at': updated.updated_at}}}


@router.post('/forgot-password', tags=['Authentication'])
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    return {'message': 'Password reset flow triggered', 'data': service.forgot_password(db, email=payload.email, request_meta=req_meta(request))}


@router.post('/reset-password', tags=['Authentication'])
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    service.reset_password(db, token=payload.token, password=payload.password, request_meta=req_meta(request))
    return {'message': 'Password reset successfully'}


@router.post('/change-password', tags=['Authentication'])
def change_password(payload: ChangePasswordRequest, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    current_refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    service.change_password(db, actor=user, payload=payload, current_refresh_token=current_refresh_token, request_meta=req_meta(request))
    return {'message': 'Password changed successfully'}


@router.post('/email/verification', tags=['Authentication'])
def email_verification(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {'message': 'Email verification issued', 'data': service.request_email_verification(db, actor=user, request_meta=req_meta(request))}


@router.post('/email/test', tags=['Authentication'])
def test_email(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {'message': 'Test email sent successfully', 'data': service.send_test_email(db, actor=user, request_meta=req_meta(request))}


@router.post('/verify-email', tags=['Authentication'])
def verify_email(payload: VerifyTokenRequest, request: Request, db: Session = Depends(get_db)):
    service.verify_email(db, token=payload.token, request_meta=req_meta(request))
    return {'message': 'Email verified successfully'}


@router.post('/verify-email/resend', tags=['Authentication'])
def resend_verify_email(payload: ResendVerificationTokenRequest, request: Request, db: Session = Depends(get_db)):
    return {'message': 'Email verification issued', 'data': service.resend_email_verification_from_token(db, token=payload.token, request_meta=req_meta(request))}


@router.post('/mfa/setup', tags=['MFA'])
def mfa_setup(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return {'message': 'MFA setup generated', 'data': mfa_service.generate_setup(db, user)}


@router.post('/mfa/verify', tags=['MFA'])
def mfa_verify(payload: MfaVerifyRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    codes = mfa_service.verify_setup(db, user, payload.token)
    return {'message': 'MFA enabled successfully', 'data': {'recovery_codes': codes}}


@router.post('/mfa/recovery-codes/regenerate', tags=['MFA'])
def regenerate_mfa_recovery_codes(payload: MfaRecoveryCodesRegenerateRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    codes = mfa_service.regenerate_recovery_codes(db, user, payload.token)
    return {'message': 'Recovery codes regenerated successfully', 'data': {'recovery_codes': codes}}


@router.post('/mfa/disable', tags=['MFA'])
def disable_mfa(payload: MfaDisableRequest, request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.core.security import verify_password
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail='Current password is incorrect')
    mfa_service.verify_login(db, user, payload.token)
    mfa_service.disable(db, user)
    service.send_security_notification_if_enabled(user, title='MFA disabled', preview='Multi-factor authentication was disabled for your Attendio account.')
    return {'message': 'MFA disabled successfully'}


@router.get('/sessions', tags=['Sessions'])
def sessions(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    items = service.list_sessions(db, actor=user)
    current_refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    current_hash = token_hash(current_refresh_token) if current_refresh_token else None
    return {'message': 'Sessions fetched successfully', 'data': [{'id': str(item.id), 'ip_address': item.ip_address, 'user_agent': item.user_agent, 'created_at': item.created_at, 'last_used_at': item.last_used_at, 'revoked_at': item.revoked_at, 'is_current': bool(current_hash and item.token_hash == current_hash), 'device_id': (item.device_info or {}).get('device_id'), 'location': ', '.join(part for part in [(item.device_info or {}).get('geo_city'), (item.device_info or {}).get('geo_country')] if part) or None} for item in items]}


@router.post('/sessions/revoke', tags=['Sessions'])
def revoke_session(payload: RevokeSessionRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    service.revoke_session(db, actor=user, session_id=payload.session_id)
    return {'message': 'Session revoked successfully'}


@router.post('/sessions/revoke-all', tags=['Sessions'])
def revoke_all_sessions(db: Session = Depends(get_db), user=Depends(get_current_user)):
    service.revoke_all_sessions(db, actor=user)
    return {'message': 'All sessions revoked successfully'}


@router.get('/audit-logs', tags=['Audit Logs'])
def audit_logs(db: Session = Depends(get_db), user=Depends(require_permissions('audit.read', 'reports.company'))):
    items = service.list_audit_logs(db, actor=user)
    return {'message': 'Audit logs fetched successfully', 'data': [{'id': str(item.id), 'action': item.action, 'entity_type': item.entity_type, 'entity_id': item.entity_id, 'payload': item.payload, 'created_at': item.created_at} for item in items]}


@router.get('/activity', tags=['Audit Logs'])
def own_activity(db: Session = Depends(get_db), user=Depends(get_current_user)):
    items = service.list_own_activity(db, actor=user)
    return {'message': 'Account activity fetched successfully', 'data': [{'id': str(item.id), 'action': item.action, 'entity_type': item.entity_type, 'payload': item.payload, 'created_at': item.created_at} for item in items]}


@router.get('/me/export', tags=['Authentication'])
def export_me(db: Session = Depends(get_db), user=Depends(get_current_user)):
    metadata = user.metadata_json or {}
    activity = service.list_own_activity(db, actor=user)
    return {'message': 'Account export generated', 'data': {'profile': {'id': str(user.id), 'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email, 'phone': user.phone, 'country': metadata.get('country'), 'city': metadata.get('city'), 'language': metadata.get('language'), 'notification_preferences': metadata.get('notification_preferences') or {}, 'mfa_enabled': user.mfa_enabled, 'created_at': user.created_at, 'updated_at': user.updated_at}, 'activity': [{'action': item.action, 'entity_type': item.entity_type, 'payload': item.payload, 'created_at': item.created_at} for item in activity]}}


@router.get('/security-policy', tags=['Authentication'])
def get_security_policy(user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'Security policy fetched successfully', 'data': service.get_security_policy(actor=user)}


@router.patch('/security-policy', tags=['Authentication'])
def update_security_policy(payload: SecurityPolicyUpdateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'Security policy updated successfully', 'data': service.update_security_policy(db, actor=user, payload=payload, request_meta=req_meta(request))}


@router.get('/security-policy/mfa-adoption', tags=['Authentication'])
def mfa_adoption(q: str = '', limit: int = 20, offset: int = 0, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    items, total = service.list_users_missing_mfa(db, actor=user, query=q, limit=min(limit, 100), offset=max(offset, 0))
    policy = service.get_security_policy(actor=user)
    return {'message': 'MFA adoption fetched successfully', 'data': {'missing_count': total, 'mfa_enforcement_at': policy.get('mfa_enforcement_at'), 'users': [{'id': str(item.id), 'name': f'{item.first_name} {item.last_name}', 'email': item.email} for item in items]}}


@router.post('/security-policy/mfa-reminders', tags=['Authentication'])
def send_mfa_reminders(payload: MfaReminderRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'MFA reminders processed', 'data': service.send_mfa_reminders(db, actor=user, user_ids=payload.user_ids, send_to_all_missing=payload.send_to_all_missing, request_meta=req_meta(request))}


@router.get('/security-policy/mfa-reminder-history', tags=['Authentication'])
def mfa_reminder_history(db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    items = service.list_mfa_reminder_history(db, actor=user)
    return {'message': 'MFA reminder history fetched successfully', 'data': [{'id': str(item.id), 'sent_count': (item.payload or {}).get('sent_count', 0), 'failed_count': (item.payload or {}).get('failed_count', 0), 'send_to_all_missing': (item.payload or {}).get('send_to_all_missing', False), 'created_at': item.created_at} for item in items]}


@router.delete('/security-policy/mfa-reminder-history', tags=['Authentication'])
def clear_mfa_reminder_history(request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'MFA reminder history cleared', 'data': service.clear_mfa_reminder_history(db, actor=user, request_meta=req_meta(request))}


@router.get('/security-policy/mfa-compliance.csv', tags=['Authentication'])
def export_mfa_compliance(db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    from io import StringIO
    import csv
    items = service.list_employees(db, actor=user)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['employee_code', 'name', 'email', 'status', 'mfa_enabled'])
    for item in items:
        writer.writerow([item.employee_code or '', f'{item.first_name} {item.last_name}', item.email, item.status, 'yes' if item.mfa_enabled else 'no'])
    return Response(content=buffer.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=mfa-compliance.csv'})




@router.get('/api-keys', tags=['API Keys'])
def list_api_keys(db: Session = Depends(get_db), user=Depends(require_permissions('api_keys.manage', 'settings.tenant'))):
    items = service.list_api_keys(db, actor=user)
    return {'message': 'API keys fetched successfully', 'data': [{'id': str(item.id), 'name': item.name, 'prefix': item.prefix, 'scopes': item.scopes, 'created_at': item.created_at, 'revoked_at': item.revoked_at} for item in items]}


@router.post('/api-keys', tags=['API Keys'])
def create_api_key(payload: CreateApiKeyRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('api_keys.manage', 'settings.tenant'))):
    value, record = service.create_api_key(db, actor=user, name=payload.name, scopes=payload.scopes, request_meta=req_meta(request))
    return {'message': 'API key created successfully', 'data': {'api_key': value, 'record': {'id': str(record.id), 'name': record.name, 'prefix': record.prefix}}}


@router.post('/api-keys/revoke', tags=['API Keys'])
def revoke_api_key(payload: RevokeApiKeyRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('api_keys.manage', 'settings.tenant'))):
    service.revoke_api_key(db, actor=user, api_key_id=payload.api_key_id, request_meta=req_meta(request))
    return {'message': 'API key revoked successfully'}


@router.post('/impersonate', tags=['Authentication'])
def impersonate(payload: ImpersonateRequest, request: Request, response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    data = service.impersonate(db, actor=user, target_user_id=payload.target_user_id, request_meta=req_meta(request))
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'], data.get('device_id'))
    return {'message': f'Impersonation started. Now acting as {data["target"].first_name} {data["target"].last_name}', 'data': {'target_user': {'id': str(data['target'].id), 'email': data['target'].email}}}


@router.get('/sso/callback', tags=['SSO'])
async def sso_callback(request: Request, response: Response, db: Session = Depends(get_db)):
    provider = request.session.pop('oauth_provider', None)
    email_hint = request.session.pop('oauth_email_hint', None)
    next_path = request.session.pop('oauth_next', None)
    expected_state = request.session.pop('oauth_state', None)
    tenant_slug = request.session.pop('oauth_tenant_slug', None)
    if provider not in {'google', 'microsoft'}:
        return cleared_session_redirect(request, frontend_url(settings.FRONTEND_SSO_ERROR, {'sso_error': 'SSO provider session is missing or expired'}))
    if request.query_params.get('error'):
        reason = request.query_params.get('error_description') or request.query_params.get('error')
        return cleared_session_redirect(request, frontend_url(settings.FRONTEND_SSO_ERROR, {'sso_error': reason}))
    if provider == 'microsoft':
        if expected_state and request.query_params.get('state') != expected_state:
            return cleared_session_redirect(request, frontend_url(settings.FRONTEND_SSO_ERROR, {'sso_error': 'Microsoft OAuth state mismatch'}))
        try:
            token = await exchange_microsoft_code(request.query_params.get('code') or '', settings.OAUTH_REDIRECT_URI)
        except HTTPException as exc:
            return cleared_session_redirect(request, frontend_url(settings.FRONTEND_SSO_ERROR, {'sso_error': str(exc.detail)}))
        profile = token.get('microsoft_profile') or {}
        email = profile.get('mail') or profile.get('userPrincipalName') or email_hint or ''
        userinfo = {
            'sub': profile.get('id'),
            'oid': profile.get('id'),
            'email': email,
            'preferred_username': email,
            'name': profile.get('displayName') or email,
        }
    else:
        client = oauth.create_client(provider) or oauth.register(name=provider, **get_provider_config(provider))
        try:
            token = await client.authorize_access_token(request)
            userinfo = token.get('userinfo')
            if not userinfo:
                userinfo = await client.userinfo(token=token)
        except OAuthError as exc:
            return cleared_session_redirect(request, frontend_url(settings.FRONTEND_SSO_ERROR, {'sso_error': oauth_error_message(provider, exc)}))
    tenant = getattr(request.state, 'tenant', None) or service.resolve_company_by_slug(db, slug=tenant_slug)
    try:
        data = service.sso_login(db, provider=provider, userinfo=dict(userinfo), tenant=tenant, email_hint=email_hint, request_meta=req_meta(request))
    except HTTPException as exc:
        return cleared_session_redirect(request, frontend_url(settings.FRONTEND_SSO_ERROR, {'sso_error': str(exc.detail)}))
    if provider == 'microsoft' and token.get('access_token'):
        save_microsoft_integration(data['company'], data['user'].email, token)
        db.add(data['company'])
        db.commit()
    redirect_url = frontend_url(next_path or settings.FRONTEND_AFTER_LOGIN, {'sso': 'success'})
    redirect_response = RedirectResponse(url=redirect_url)
    set_auth_cookies(redirect_response, data['access_token'], data['refresh_token'], data['company'], data.get('device_id'))
    request.session.clear()
    return redirect_response


@router.get('/sso/{provider}', tags=['SSO'])
async def start_sso(provider: str, request: Request):
    provider = provider.lower().strip()
    if provider == 'saml':
        raise HTTPException(status_code=501, detail='SAML SSO requires a dedicated SAML flow and is not enabled yet')
    config = get_provider_config(provider)
    request.session['oauth_provider'] = provider
    if request.query_params.get('email'):
        request.session['oauth_email_hint'] = request.query_params['email']
    if request.query_params.get('next'):
        request.session['oauth_next'] = request.query_params['next']
    if request.query_params.get('tenant'):
        request.session['oauth_tenant_slug'] = request.query_params['tenant']
    if provider == 'microsoft':
        state = secrets.token_urlsafe(24)
        request.session['oauth_state'] = state
        tenant = microsoft_authority()
        authorize_url = f'{MICROSOFT_AUTHORIZE_URL.format(tenant=tenant)}?{urlencode({
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.OAUTH_REDIRECT_URI,
            "response_mode": "query",
            "scope": MICROSOFT_GRAPH_SCOPE,
            "state": state,
            "prompt": "consent",
        })}'
        return RedirectResponse(url=authorize_url)
    client = oauth.create_client(provider) or oauth.register(name=provider, **config)
    redirect_uri = settings.OAUTH_REDIRECT_URI
    extra_params = {'prompt': 'consent', 'scope': config['client_kwargs']['scope']} if provider == 'microsoft' else {'scope': config['client_kwargs']['scope']}
    return await client.authorize_redirect(request, redirect_uri, **extra_params)
