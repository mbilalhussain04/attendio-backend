import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow, onupdate=datetime.utcnow)


class LeavePolicy(TimestampMixin, Base):
    __tablename__ = "leave_policies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    approval_levels: Mapped[int] = mapped_column(Integer, default=1)
    count_weekends: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_negative_balance: Mapped[bool] = mapped_column(Boolean, default=False)
    half_day_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LeaveType(TimestampMixin, Base):
    __tablename__ = "leave_types"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_leave_type_company_code"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(255))
    entitlement_days: Mapped[float | None] = mapped_column(Numeric(7, 2), nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=True)
    attachment_required: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeaveEntitlementPolicy(TimestampMixin, Base):
    __tablename__ = "leave_entitlement_policies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    leave_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_types.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    contract_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entitlement_days: Mapped[float] = mapped_column(Numeric(7, 2))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    leave_type: Mapped["LeaveType"] = relationship()


class LeaveEntitlementGrant(TimestampMixin, Base):
    __tablename__ = "leave_entitlement_grants"
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", "leave_type_id", "year", name="uq_leave_grant_company_user_type_year"),
        Index("ix_leave_grants_company_user_year", "company_id", "user_id", "year"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    leave_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_types.id"), index=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_entitlement_policies.id"), nullable=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    entitlement_days: Mapped[float] = mapped_column(Numeric(7, 2))
    source: Mapped[str] = mapped_column(String(32), default="policy")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    leave_type: Mapped["LeaveType"] = relationship()
    policy: Mapped["LeaveEntitlementPolicy | None"] = relationship()


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        Index("ix_leave_requests_company_user_year", "company_id", "user_id", "year"),
        Index("ix_leave_requests_company_status", "company_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    employee_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    leave_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_types.id"))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    year: Mapped[int] = mapped_column(Integer, index=True)
    session: Mapped[str] = mapped_column(String(20), default="full_day")
    total_days: Mapped[float] = mapped_column(Numeric(7, 2))
    reason: Mapped[str] = mapped_column(Text)
    attachment_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    leave_type: Mapped["LeaveType"] = relationship()
    approvals: Mapped[list["LeaveApproval"]] = relationship(back_populates="request", cascade="all, delete-orphan")


class LeaveApproval(TimestampMixin, Base):
    __tablename__ = "leave_approvals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_requests.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    request: Mapped["LeaveRequest"] = relationship(back_populates="approvals")
