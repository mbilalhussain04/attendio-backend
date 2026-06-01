from uuid import uuid4
from base64 import b64encode
import json
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import SessionLocal
from app.main import app
from app.api.routes import auth as auth_routes
from app.models.company import Company
from app.models.role import Role
from app.models.user import User
from app.models.verification_token import VerificationToken
from app.services.auth import service


def ensure_system_roles():
    with SessionLocal() as db:
        roles = {
            role.key
            for role in db.execute(select(Role).where(Role.company_id.is_(None))).scalars().all()
        }
        if 'employee' not in roles:
            db.add(Role(key='employee', name='Employee', description='Default employee', is_system=True))
        if 'company_owner' not in roles:
            db.add(Role(key='company_owner', name='Company Owner', description='Owns the company', is_system=True))
            db.commit()


def create_user(email: str, *, provider: str = 'local', metadata_json: dict | None = None):
    ensure_system_roles()
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.key == 'employee', Role.company_id.is_(None)))
        slug = f'test-{uuid4().hex[:10]}'
        company = Company(name=f'Test {email}', slug=slug, domain=f'{slug}.lvh.me')
        db.add(company)
        db.flush()
        user = User(
            company_id=company.id,
            employee_code='EMP-000001',
            first_name='Test',
            last_name='User',
            email=email,
            password_hash=hash_password('Password123') if provider == 'local' else None,
            provider=provider,
            status='active',
            email_verified=provider != 'local',
            metadata_json=metadata_json or {},
        )
        user.roles.append(role)
        db.add(user)
        db.commit()
        return user.id, company.id


def signed_session_cookie(data: dict) -> str:
    payload = b64encode(json.dumps(data).encode('utf-8'))
    return TimestampSigner(settings.SECRET_KEY).sign(payload).decode('utf-8')


def test_sso_callback_route_redirects_when_session_is_missing():
    client = TestClient(app, follow_redirects=False)

    response = client.get('/api/v1/auth/sso/callback')

    assert response.status_code == 307
    assert response.headers['location'].startswith(f'{settings.FRONTEND_BASE_URL}/sign-in?')
    assert 'sso_error=' in response.headers['location']


def test_google_sso_links_existing_local_account_without_replacing_password_login():
    email = f'local-google-link-{uuid4().hex[:10]}@example.com'
    user_id, _ = create_user(email)

    with SessionLocal() as db:
        data = service.sso_login(
            db,
            provider='google',
            userinfo={'email': email, 'email_verified': True, 'sub': 'google-sub-123', 'name': 'Test User'},
            tenant=None,
            email_hint=None,
            request_meta={},
        )
        user = db.get(User, user_id)

        assert data['user'].id == user_id
        assert user.provider == 'local'
        assert user.email_verified is True
        assert user.metadata_json['sso']['provider'] == 'google'
        assert verify_password('Password123', user.password_hash)


def test_google_sso_auto_provisions_new_company_owner(monkeypatch):
    ensure_system_roles()
    email = f'fresh-google-{uuid4().hex[:10]}@example.com'
    monkeypatch.setattr('app.services.auth.settings.SSO_AUTO_PROVISION', True)

    with SessionLocal() as db:
        data = service.sso_login(
            db,
            provider='google',
            userinfo={'email': email, 'email_verified': True, 'sub': 'fresh-google-sub', 'name': 'Fresh User'},
            tenant=None,
            email_hint=None,
            request_meta={},
        )

        user = db.get(User, data['user'].id)
        assert user.email == email
        assert user.provider == 'google'
        assert user.password_hash is None
        assert user.email_verified is True
        assert [role.key for role in user.roles] == ['company_owner']
        assert user.company.metadata_json['created_by'] == 'sso_signup'


def test_google_auto_provisioned_user_can_reset_password_and_login(monkeypatch):
    ensure_system_roles()
    email = f'fresh-google-reset-{uuid4().hex[:10]}@example.com'
    monkeypatch.setattr('app.services.auth.settings.SSO_AUTO_PROVISION', True)
    monkeypatch.setattr('app.services.auth.publish_event', lambda *args, **kwargs: False)

    with SessionLocal() as db:
        service.sso_login(
            db,
            provider='google',
            userinfo={'email': email, 'email_verified': True, 'sub': 'fresh-google-reset-sub', 'name': 'Fresh Reset'},
            tenant=None,
            email_hint=None,
            request_meta={},
        )
        reset = service.forgot_password(db, email=email, request_meta={})
        token = parse_qs(urlparse(reset['development_link']).query)['token'][0]
        service.reset_password(db, token=token, password='NewPassword123', request_meta={})
        login = service.login(db, email=email, password='NewPassword123', mfa_token=None, tenant=None, request_meta={})

        assert login['user'].email == email


def test_google_sso_callback_links_existing_local_account(monkeypatch):
    email = f'callback-link-{uuid4().hex[:10]}@example.com'
    user_id, _ = create_user(email)

    class FakeOAuthClient:
        async def authorize_access_token(self, request):
            return {
                'userinfo': {
                    'email': email,
                    'email_verified': True,
                    'sub': 'google-sub-callback',
                    'name': 'Callback User',
                }
            }

    monkeypatch.setattr(auth_routes.oauth, 'create_client', lambda provider: FakeOAuthClient())

    client = TestClient(app, follow_redirects=False)
    client.cookies.set(
        'session',
        signed_session_cookie({'oauth_provider': 'google', 'oauth_next': '/dashboard'}),
        path='/',
    )

    response = client.get('/api/v1/auth/sso/callback?state=test&code=test')

    assert response.status_code == 307
    assert response.headers['location'] == f'{settings.FRONTEND_BASE_URL}/dashboard?sso=success'
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.metadata_json['sso']['provider'] == 'google'


def test_forgot_password_does_not_create_reset_token_for_sso_only_account(monkeypatch):
    email = f'google-only-{uuid4().hex[:10]}@example.com'
    user_id, _ = create_user(email, provider='google')
    monkeypatch.setattr('app.services.auth.settings.ALLOW_EMAIL_LOGIN_FALLBACK', False)

    with SessionLocal() as db:
        response = service.forgot_password(db, email=email, request_meta={})
        token = db.scalar(select(VerificationToken).where(VerificationToken.user_id == user_id))

        assert response == {'sent': True}
        assert token is None
