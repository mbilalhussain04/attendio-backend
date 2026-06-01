from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.role import Role


def ensure_company_owner_role():
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.key == 'company_owner', Role.company_id.is_(None)))
        if not role:
            db.add(Role(key='company_owner', name='Company Owner', description='Owns the company', is_system=True))
            db.commit()


def test_bootstrap_requires_email_verification_before_login(monkeypatch):
    ensure_company_owner_role()
    monkeypatch.setattr('app.services.auth.publish_event', lambda *args, **kwargs: True)

    client = TestClient(app)
    suffix = uuid4().hex[:10]
    email = f'owner-{suffix}@example.com'
    password = 'Admin@12345'

    bootstrap = client.post(
        '/api/v1/auth/bootstrap-company',
        json={
            'company_name': f'Verify Flow {suffix}',
            'owner_first_name': 'Owner',
            'owner_last_name': 'Admin',
            'owner_email': email,
            'owner_password': password,
        },
    )

    assert bootstrap.status_code == 200
    assert bootstrap.json()['data']['email_verification']['sent'] is True

    login = client.post('/api/v1/auth/login', json={'email': email, 'password': password})

    assert login.status_code == 403
    assert login.json()['detail'] == 'Email verification required. We sent a fresh verification link to your email.'
