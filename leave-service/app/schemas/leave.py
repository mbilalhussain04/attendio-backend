from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    approval_levels: int
    count_weekends: bool
    allow_negative_balance: bool
    half_day_enabled: bool


class PolicyUpdateIn(BaseModel):
    approval_levels: int | None = Field(default=None, ge=1, le=4)
    count_weekends: bool | None = None
    allow_negative_balance: bool | None = None
    half_day_enabled: bool | None = None


class LeaveTypeIn(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=255)
    entitlement_days: float | None = Field(default=None, ge=0, le=366)
    paid: bool = True
    attachment_required: bool = False
    active: bool = True


class LeaveTypeOut(LeaveTypeIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID


class EntitlementPolicyIn(BaseModel):
    leave_type_id: UUID
    name: str = Field(min_length=2, max_length=255)
    contract_type: str | None = Field(default=None, max_length=80)
    employment_type: str | None = Field(default=None, max_length=80)
    entitlement_days: float = Field(ge=0, le=366)
    priority: int = Field(default=100, ge=1, le=1000)
    active: bool = True


class EntitlementPolicyOut(EntitlementPolicyIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    leave_type: LeaveTypeOut


class EntitlementGrantIn(BaseModel):
    user_id: UUID
    leave_type_id: UUID
    year: int = Field(ge=1970, le=2100)
    entitlement_days: float = Field(ge=0, le=366)
    note: str | None = Field(default=None, max_length=1000)
    employee_snapshot: dict | None = None


class EntitlementGrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    user_id: UUID
    leave_type_id: UUID
    policy_id: UUID | None
    year: int
    entitlement_days: float
    source: str
    note: str | None
    employee_snapshot: dict | None
    leave_type: LeaveTypeOut


class LeaveRequestIn(BaseModel):
    leave_type_id: UUID
    from_date: date
    to_date: date
    session: Literal["full_day", "half_day"] = "full_day"
    reason: str = Field(default="", max_length=1000)
    attachment_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        if self.session == "half_day" and self.to_date != self.from_date:
            raise ValueError("half-day requests must use one date")
        return self


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    level: int
    reviewer_user_id: UUID | None
    status: str
    note: str | None
    decided_at: datetime | None


class LeaveRequestBalanceOut(BaseModel):
    leave_type_id: UUID
    code: str
    name: str
    paid: bool
    entitlement_days: float | None
    taken_days: float
    pending_days: float
    available_days: float | None


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    user_id: UUID
    employee_snapshot: dict | None
    leave_type: LeaveTypeOut
    from_date: date
    to_date: date
    year: int
    session: str
    total_days: float
    reason: str
    attachment_urls: list | None
    status: str
    decided_by_user_id: UUID | None
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime
    approvals: list[ApprovalOut] = []
    balance: LeaveRequestBalanceOut | None = None


class ReviewIn(BaseModel):
    status: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class BalanceOut(BaseModel):
    leave_type_id: UUID
    code: str
    name: str
    paid: bool
    entitlement_days: float | None
    taken_days: float
    pending_days: float
    available_days: float | None
