from datetime import date

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.deps.auth import AuthContext, require_permissions
from app.deps.db import get_db
from app.schemas.leave import BalanceOut, EntitlementGrantIn, EntitlementGrantOut, EntitlementPolicyIn, EntitlementPolicyOut, LeaveRequestIn, LeaveRequestOut, LeaveTypeIn, LeaveTypeOut, PolicyOut, PolicyUpdateIn, ReviewIn
from app.services import leave_service
from app.core.config import settings
from app.utils.permissions import Permissions

router = APIRouter(prefix="/api/v1/leave")


def ok(data, message: str | None = None):
    body = {"success": True, "data": data}
    if message:
        body["message"] = message
    return body


def profile_snapshot(auth: AuthContext):
    user = (auth.profile or {}).get("user", auth.profile or {})
    return {
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "email": user.get("email") or auth.email,
        "employee_code": user.get("employee_code"),
        "job_title": user.get("job_title"),
        "department": user.get("department"),
        "contract_type": user.get("contract_type"),
        "employment_type": user.get("employment_type"),
    }


def public_holiday_dates(request: Request):
    if not settings.ATTENDANCE_SERVICE_URL:
        return set()
    headers = {}
    if request.headers.get("authorization"):
        headers["authorization"] = request.headers["authorization"]
    if request.headers.get("cookie"):
        headers["cookie"] = request.headers["cookie"]
    try:
        result = httpx.get(f"{settings.ATTENDANCE_SERVICE_URL.rstrip('/')}/api/v1/attendance/holidays", headers=headers, timeout=3)
        if result.is_success:
            return {date.fromisoformat(item["holiday_date"]) for item in result.json().get("data", []) if item.get("holiday_date") and item.get("category") == "public"}
    except httpx.HTTPError:
        pass
    return set()


@router.get("/health", tags=["Health"])
def api_health():
    return {"status": "ok", "service": "leave-service"}


@router.get("/policy", tags=["Leave configuration"])
def get_policy(db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    return ok(PolicyOut.model_validate(leave_service.get_policy(db, auth.company_id)))


@router.put("/policy", tags=["Leave configuration"])
def put_policy(payload: PolicyUpdateIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.update_policy(db, auth.company_id, payload.model_dump(exclude_none=True))
    db.commit()
    db.refresh(row)
    return ok(PolicyOut.model_validate(row))


@router.get("/types", tags=["Leave configuration"])
def get_types(include_inactive: bool = False, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_VIEW_SELF))):
    return ok([LeaveTypeOut.model_validate(row) for row in leave_service.list_types(db, auth.company_id, include_inactive=include_inactive and Permissions.LEAVE_CONFIGURE in auth.permissions)])


@router.post("/types", tags=["Leave configuration"])
def post_type(payload: LeaveTypeIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.upsert_type(db, auth.company_id, payload.model_dump())
    db.commit()
    db.refresh(row)
    return ok(LeaveTypeOut.model_validate(row))


@router.put("/types/{type_id}", tags=["Leave configuration"])
def put_type(type_id: str, payload: LeaveTypeIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.upsert_type(db, auth.company_id, payload.model_dump(), type_id=type_id)
    db.commit()
    db.refresh(row)
    return ok(LeaveTypeOut.model_validate(row))


@router.delete("/types/{type_id}", tags=["Leave configuration"])
def delete_type(type_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.archive_type(db, auth.company_id, type_id)
    db.commit()
    db.refresh(row)
    return ok(LeaveTypeOut.model_validate(row), "Leave type archived")


@router.get("/entitlement-policies", tags=["Leave configuration"])
def get_entitlement_policies(include_inactive: bool = False, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    return ok([EntitlementPolicyOut.model_validate(row) for row in leave_service.list_entitlement_policies(db, auth.company_id, include_inactive=include_inactive)])


@router.post("/entitlement-policies", tags=["Leave configuration"])
def post_entitlement_policy(payload: EntitlementPolicyIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.upsert_entitlement_policy(db, auth.company_id, payload.model_dump())
    db.commit()
    db.refresh(row)
    return ok(EntitlementPolicyOut.model_validate(row))


@router.put("/entitlement-policies/{policy_id}", tags=["Leave configuration"])
def put_entitlement_policy(policy_id: str, payload: EntitlementPolicyIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.upsert_entitlement_policy(db, auth.company_id, payload.model_dump(), policy_id=policy_id)
    db.commit()
    db.refresh(row)
    return ok(EntitlementPolicyOut.model_validate(row))


@router.delete("/entitlement-policies/{policy_id}", tags=["Leave configuration"])
def delete_entitlement_policy(policy_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.archive_entitlement_policy(db, auth.company_id, policy_id)
    db.commit()
    db.refresh(row)
    return ok(EntitlementPolicyOut.model_validate(row), "Entitlement policy archived")


@router.get("/entitlement-grants", tags=["Leave configuration"])
def get_entitlement_grants(user_id: str | None = None, year: int | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    return ok([EntitlementGrantOut.model_validate(row) for row in leave_service.list_grants(db, auth.company_id, user_id=user_id, year=year)])


@router.post("/entitlement-grants", tags=["Leave configuration"])
def post_entitlement_grant(payload: EntitlementGrantIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.upsert_grant(db, auth.company_id, payload.model_dump(), source="override")
    db.commit()
    db.refresh(row)
    return ok(EntitlementGrantOut.model_validate(row))


@router.put("/entitlement-grants/{grant_id}", tags=["Leave configuration"])
def put_entitlement_grant(grant_id: str, payload: EntitlementGrantIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    row = leave_service.upsert_grant(db, auth.company_id, payload.model_dump(), source="override", grant_id=grant_id)
    db.commit()
    db.refresh(row)
    return ok(EntitlementGrantOut.model_validate(row))


@router.delete("/entitlement-grants/{grant_id}", tags=["Leave configuration"])
def delete_entitlement_grant(grant_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_CONFIGURE))):
    result = leave_service.delete_grant(db, auth.company_id, grant_id)
    db.commit()
    return ok(result)


@router.get("/me/requests", tags=["Leave requests"])
def my_requests(year: int | None = None, status: str | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_VIEW_SELF))):
    return ok([LeaveRequestOut.model_validate(row) for row in leave_service.list_requests(db, auth.company_id, user_id=auth.user_id, year=year, status=status)])


@router.post("/me/requests", tags=["Leave requests"])
def post_request(payload: LeaveRequestIn, request: Request, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_REQUEST))):
    row = leave_service.create_request(db, auth.company_id, auth.user_id, payload.model_dump(), employee_snapshot=profile_snapshot(auth), excluded_dates=public_holiday_dates(request))
    db.commit()
    db.refresh(row)
    return ok(LeaveRequestOut.model_validate(row), "Leave request submitted")


@router.post("/me/requests/{request_id}/cancel", tags=["Leave requests"])
def cancel_request(request_id: str, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_REQUEST))):
    row = leave_service.cancel_request(db, auth.company_id, auth.user_id, request_id)
    db.commit()
    db.refresh(row)
    return ok(LeaveRequestOut.model_validate(row), "Leave request cancelled")


@router.get("/me/balance", tags=["Leave requests"])
def my_balance(year: int | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_VIEW_SELF))):
    rows = leave_service.balance_rows(db, auth.company_id, auth.user_id, year or date.today().year, profile=auth.profile, employee_snapshot=profile_snapshot(auth))
    db.commit()
    return ok([BalanceOut.model_validate(row) for row in rows])


@router.get("/requests", tags=["Leave review"])
def company_requests(year: int | None = None, status: str | None = None, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_VIEW_COMPANY))):
    rows = leave_service.list_requests(db, auth.company_id, year=year, status=status)
    balances = {}
    output = []
    for row in rows:
        key = (str(row.user_id), row.year)
        if key not in balances:
            balances[key] = leave_service.balance_rows(
                db,
                auth.company_id,
                str(row.user_id),
                row.year,
                profile=row.employee_snapshot,
                employee_snapshot=row.employee_snapshot,
            )
        balance = next((item for item in balances[key] if item["leave_type_id"] == row.leave_type_id), None)
        output.append(LeaveRequestOut.model_validate(row).model_copy(update={"balance": BalanceOut.model_validate(balance) if balance else None}))
    db.commit()
    return ok(output)


@router.post("/requests/{request_id}/review", tags=["Leave review"])
def review(request_id: str, payload: ReviewIn, db: Session = Depends(get_db), auth: AuthContext = Depends(require_permissions(Permissions.LEAVE_REVIEW))):
    row = leave_service.review_request(db, auth.company_id, auth.user_id, request_id, payload.status, payload.note)
    db.commit()
    db.refresh(row)
    return ok(LeaveRequestOut.model_validate(row), f"Leave request {payload.status}")
