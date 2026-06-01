import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, JSON, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.associations import UserRole


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (
        UniqueConstraint('company_id', 'email', name='users_company_email_uq'),
        UniqueConstraint('company_id', 'employee_code', name='users_company_employee_code_uq'),
        UniqueConstraint('company_id', 'external_employee_id', name='users_company_external_employee_id_uq'),
        UniqueConstraint('company_id', 'payroll_employee_id', name='users_company_payroll_employee_id_uq'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    keycloak_user_id: Mapped[str | None] = mapped_column(String(64))
    employee_code: Mapped[str | None] = mapped_column(String(80))
    external_employee_id: Mapped[str | None] = mapped_column(String(80))
    payroll_employee_id: Mapped[str | None] = mapped_column(String(80))
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(20), default='local', nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='active', nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(255))
    login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    company = relationship('Company', back_populates='users')
    roles = relationship('Role', secondary=UserRole.__table__, back_populates='users')
