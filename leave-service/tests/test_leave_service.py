import uuid
from datetime import date

import pytest

from app.db.session import SessionLocal
from app.services import leave_service
from app.utils.permissions import Permissions


def test_permissions_present():
    assert Permissions.LEAVE_REQUEST
    assert Permissions.LEAVE_REVIEW


def test_work_days_exclude_configured_public_holidays():
    assert leave_service.work_days(
        date(2026, 5, 11),
        date(2026, 5, 15),
        count_weekends=False,
        excluded_dates={date(2026, 5, 14)},
    ) == 4


def test_leave_type_code_is_generated_from_name():
    with SessionLocal() as db:
        leave_type = leave_service.upsert_type(db, str(uuid.uuid4()), {
            "name": "Annual Leave",
            "entitlement_days": 20,
            "paid": True,
            "attachment_required": False,
            "active": True,
        })
        assert leave_type.code == "annual-leave"


def test_entitlement_policy_materializes_contract_grant_for_balance():
    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with SessionLocal() as db:
        leave_type = leave_service.upsert_type(db, company_id, {
            "name": "Paid Leave",
            "entitlement_days": 30,
            "paid": True,
            "attachment_required": False,
            "active": True,
        })
        leave_service.upsert_entitlement_policy(db, company_id, {
            "leave_type_id": leave_type.id,
            "name": "Intern leave",
            "contract_type": "intern",
            "employment_type": None,
            "entitlement_days": 7,
            "priority": 10,
            "active": True,
        })

        balance = leave_service.balance_rows(
            db,
            company_id,
            user_id,
            2026,
            profile={"contract_type": "intern", "employment_type": "onsite"},
            employee_snapshot={"contract_type": "intern", "employment_type": "onsite"},
        )[0]
        grant = leave_service.list_grants(db, company_id, user_id=user_id, year=2026)[0]

        assert balance["entitlement_days"] == 7
        assert grant.source == "policy"
        assert grant.employee_snapshot["contract_type"] == "intern"


def test_manual_entitlement_grant_overrides_policy_grant():
    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with SessionLocal() as db:
        leave_type = leave_service.upsert_type(db, company_id, {
            "name": "Vacation",
            "entitlement_days": 20,
            "paid": True,
            "attachment_required": False,
            "active": True,
        })
        leave_service.upsert_entitlement_policy(db, company_id, {
            "leave_type_id": leave_type.id,
            "name": "Permanent allowance",
            "contract_type": "permanent_full_time",
            "employment_type": None,
            "entitlement_days": 20,
            "priority": 10,
            "active": True,
        })
        leave_service.balance_rows(db, company_id, user_id, 2026, profile={"contract_type": "permanent_full_time"})

        leave_service.upsert_grant(db, company_id, {
            "user_id": user_id,
            "leave_type_id": leave_type.id,
            "year": 2026,
            "entitlement_days": 25,
            "employee_snapshot": {"contract_type": "permanent_full_time"},
            "note": "Special carry entitlement",
        })

        balance = leave_service.balance_rows(db, company_id, user_id, 2026, profile={"contract_type": "permanent_full_time"})[0]
        grant = leave_service.list_grants(db, company_id, user_id=user_id, year=2026)[0]

        assert balance["entitlement_days"] == 25
        assert grant.source == "override"
        assert grant.note == "Special carry entitlement"


def test_request_balance_and_review_flow():
    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    with SessionLocal() as db:
        leave_service.update_policy(db, company_id, {"approval_levels": 2, "count_weekends": False})
        leave_type = leave_service.upsert_type(db, company_id, {
            "code": "vacation",
            "name": "Vacation",
            "entitlement_days": 20,
            "paid": True,
            "attachment_required": False,
            "active": True,
        })
        request = leave_service.create_request(db, company_id, user_id, {
            "leave_type_id": leave_type.id,
            "from_date": date(2026, 5, 21),
            "to_date": date(2026, 5, 25),
            "session": "full_day",
            "reason": "Family travel",
            "attachment_urls": [],
        })
        db.commit()
        assert float(request.total_days) == 3
        assert len(request.approvals) == 2
        balance = leave_service.balance_rows(db, company_id, user_id, 2026)[0]
        assert balance["pending_days"] == 3
        assert balance["available_days"] == 17

        leave_service.review_request(db, company_id, reviewer_id, str(request.id), "approved", "manager approved")
        db.commit()
        assert request.status == "pending"
        leave_service.review_request(db, company_id, reviewer_id, str(request.id), "approved", "hr approved")
        db.commit()
        assert request.status == "approved"
        balance = leave_service.balance_rows(db, company_id, user_id, 2026)[0]
        assert balance["taken_days"] == 3
        assert balance["pending_days"] == 0


def test_overlap_is_rejected():
    company_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    with SessionLocal() as db:
        leave_type = leave_service.upsert_type(db, company_id, {
            "code": "sick",
            "name": "Sick",
            "entitlement_days": None,
            "paid": True,
            "attachment_required": False,
            "active": True,
        })
        payload = {
            "leave_type_id": leave_type.id,
            "from_date": date(2026, 7, 6),
            "to_date": date(2026, 7, 6),
            "session": "full_day",
            "reason": "Unwell",
            "attachment_urls": [],
        }
        leave_service.create_request(db, company_id, user_id, payload)
        db.commit()
        with pytest.raises(Exception):
            leave_service.create_request(db, company_id, user_id, payload)
