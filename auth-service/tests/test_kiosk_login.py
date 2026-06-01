from uuid import uuid4

from sqlalchemy import select

from app.core.security import token_hash
from app.db.session import SessionLocal
from app.models.company import Company
from app.models.user import User
from app.services.auth import service


def test_set_kiosk_pin_persists_for_user_with_existing_metadata():
    suffix = uuid4().hex[:10]

    with SessionLocal() as db:
        company = Company(
            name=f'Kiosk {suffix}',
            slug=f'kiosk-{suffix}',
            domain=f'kiosk-{suffix}.lvh.me',
        )
        db.add(company)
        db.flush()

        actor = User(
            company_id=company.id,
            employee_code=f'OWNER-{suffix}',
            first_name='Kiosk',
            last_name='Owner',
            email=f'kiosk-owner-{suffix}@example.com',
            status='active',
            metadata_json={},
        )
        employee = User(
            company_id=company.id,
            employee_code=f'EMP-{suffix}',
            first_name='Kiosk',
            last_name='Employee',
            email=f'kiosk-employee-{suffix}@example.com',
            status='active',
            metadata_json={'department': 'Reception'},
        )
        db.add_all([actor, employee])
        db.commit()

        employee_id = employee.id
        service.set_kiosk_pin(
            db,
            actor=actor,
            target_user_id=employee_id,
            pin='1234',
            request_meta={},
        )

    with SessionLocal() as db:
        employee = db.scalar(select(User).where(User.id == employee_id))

        assert employee.metadata_json['department'] == 'Reception'
        assert employee.metadata_json['kiosk_pin_hash'] == token_hash('1234')
