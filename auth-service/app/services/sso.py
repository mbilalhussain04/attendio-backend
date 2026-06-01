from fastapi import HTTPException
from authlib.integrations.starlette_client import OAuth
from app.core.config import settings


oauth = OAuth()
MICROSOFT_GRAPH_SCOPE = 'openid email profile offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Calendars.ReadWrite'


def microsoft_authority() -> str:
    authority = (settings.MICROSOFT_AUTHORITY or 'common').strip()
    if authority.lower() in {'tenant', 'single_tenant', 'tenant_specific'}:
        return settings.MICROSOFT_TENANT_ID or 'common'
    if authority.lower() in {'common', 'organizations', 'consumers'}:
        return authority.lower()
    return authority


def get_provider_config(provider: str):
    if provider == 'google':
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=501, detail='Google SSO is not configured')
        return {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'server_metadata_url': 'https://accounts.google.com/.well-known/openid-configuration',
            'client_kwargs': {'scope': 'openid email profile'},
        }
    if provider == 'microsoft':
        if not settings.MICROSOFT_CLIENT_ID or not settings.MICROSOFT_CLIENT_SECRET:
            raise HTTPException(status_code=501, detail='Microsoft SSO is not configured')
        return {
            'client_id': settings.MICROSOFT_CLIENT_ID,
            'client_secret': settings.MICROSOFT_CLIENT_SECRET,
            'server_metadata_url': f'https://login.microsoftonline.com/{microsoft_authority()}/v2.0/.well-known/openid-configuration',
            'client_kwargs': {'scope': MICROSOFT_GRAPH_SCOPE},
        }
    if provider == 'saml':
        # SAML SSO configuration - requires SAML metadata URL and certificates
        if not settings.SAML_METADATA_URL:
            raise HTTPException(status_code=501, detail='SAML SSO is not configured')
        return {
            'client_id': settings.SAML_ENTITY_ID or 'attendio-saml',
            'client_secret': settings.SAML_CERTIFICATE or '',
            'server_metadata_url': settings.SAML_METADATA_URL,
            'client_kwargs': {'scope': 'openid email profile'},
        }
    raise HTTPException(status_code=400, detail='Unsupported SSO provider')
