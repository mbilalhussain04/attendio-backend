import uuid
from datetime import date, datetime, time
from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Time, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ShiftTemplate(Base):
    __tablename__ = 'shift_templates'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    code: Mapped[str | None] = mapped_column(String(40))
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(100))
    location_id: Mapped[str | None] = mapped_column(String(80))
    department_id: Mapped[str | None] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20), default='active', nullable=False)
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class RosterTemplate(Base):
    __tablename__ = 'roster_templates'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    shift_template_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('shift_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    days_of_week: Mapped[list] = mapped_column(JSON, default=list)
    employee_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default='active', nullable=False)
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduleAssignment(Base):
    __tablename__ = 'schedule_assignments'
    __table_args__ = (
        Index('ix_schedule_assignments_company_date_employee', 'company_id', 'work_date', 'employee_id'),
        Index('ix_schedule_assignments_company_status_date', 'company_id', 'status', 'work_date'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    shift_template_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('shift_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default='scheduled', nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class MeetingEvent(Base):
    __tablename__ = 'meeting_events'
    __table_args__ = (
        Index('ix_meeting_events_company_date_employee', 'company_id', 'work_date', 'employee_id'),
        Index('ix_meeting_events_company_status_date', 'company_id', 'status', 'work_date'),
        Index('ix_meeting_events_company_external', 'company_id', 'external_provider', 'external_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    color: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20), default='published', nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200))
    attendee_emails: Mapped[list] = mapped_column(JSON, default=list)
    repeat_rule: Mapped[str | None] = mapped_column(String(80))
    external_provider: Mapped[str | None] = mapped_column(String(80), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    external_link: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(40), default='manual', nullable=False)
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
