import uuid
from datetime import datetime, date
from sqlalchemy import String, Text, Integer, Boolean, DateTime, Date, ForeignKey, UniqueConstraint, Index, Numeric, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyPolicy(TimestampMixin, Base):
    __tablename__ = 'company_policies'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(100), default='Europe/Berlin')
    daily_target_hours: Mapped[float] = mapped_column(Numeric(5,2), default=8)
    weekly_hours: Mapped[float] = mapped_column(Numeric(5,2), default=40)
    max_daily_hours: Mapped[float] = mapped_column(Numeric(5,2), default=10)
    max_weekly_average_hours: Mapped[float] = mapped_column(Numeric(5,2), default=48)
    break_after_6h_minutes: Mapped[int] = mapped_column(Integer, default=30)
    break_after_9h_minutes: Mapped[int] = mapped_column(Integer, default=45)
    rest_period_hours: Mapped[int] = mapped_column(Integer, default=11)
    late_grace_minutes: Mapped[int] = mapped_column(Integer, default=15)
    auto_insert_breaks: Mapped[bool] = mapped_column(Boolean, default=False)
    sunday_justification_required: Mapped[bool] = mapped_column(Boolean, default=True)
    require_geofence_on_mobile: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_after_days: Mapped[int] = mapped_column(Integer, default=30)
    payroll_round_to_minutes: Mapped[int] = mapped_column(Integer, default=15)
    daily_grace_early_departure_minutes: Mapped[int] = mapped_column(Integer, default=0)
    federal_state: Mapped[str] = mapped_column(String(20), default='DE-BE')


class AttendanceEntry(TimestampMixin, Base):
    __tablename__ = 'attendance_entries'
    __table_args__ = (
        Index('ix_attendance_entries_company_user_date', 'company_id', 'user_id', 'date'),
        Index('ix_attendance_entries_company_date', 'company_id', 'date'),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    employee_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default='web')
    status: Mapped[str] = mapped_column(String(20), default='open')
    date: Mapped[date] = mapped_column(Date, index=True)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    target_work_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_departure_minutes: Mapped[int] = mapped_column(Integer, default=0)
    absence_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manual_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    breaks: Mapped[list['AttendanceBreak']] = relationship(back_populates='entry', cascade='all, delete-orphan')
    flags: Mapped[list['AttendanceFlag']] = relationship(back_populates='entry', cascade='all, delete-orphan')
    corrections: Mapped[list['AttendanceCorrectionRequest']] = relationship(back_populates='entry', cascade='all, delete-orphan')
    approvals: Mapped[list['AttendanceApproval']] = relationship(back_populates='entry', cascade='all, delete-orphan')
    source_events: Mapped[list['AttendanceSourceEvent']] = relationship(back_populates='entry', cascade='all, delete-orphan')


class AttendanceBreak(TimestampMixin, Base):
    __tablename__ = 'attendance_breaks'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attendance_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('attendance_entries.id'))
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default='web')
    entry: Mapped['AttendanceEntry'] = relationship(back_populates='breaks')


class AttendanceFlag(TimestampMixin, Base):
    __tablename__ = 'attendance_flags'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attendance_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('attendance_entries.id'))
    flag_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20), default='info')
    message: Mapped[str] = mapped_column(String(255))
    entry: Mapped['AttendanceEntry'] = relationship(back_populates='flags')


class AttendanceCorrectionRequest(TimestampMixin, Base):
    __tablename__ = 'attendance_correction_requests'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attendance_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('attendance_entries.id'))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    correction_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requester_timezone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    requested_check_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requested_check_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requested_break_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_check_in_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_check_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    original_break_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entry: Mapped['AttendanceEntry'] = relationship(back_populates='corrections')


class AttendanceApproval(TimestampMixin, Base):
    __tablename__ = 'attendance_approvals'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    attendance_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('attendance_entries.id'))
    level: Mapped[int] = mapped_column(Integer, default=1)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry: Mapped['AttendanceEntry'] = relationship(back_populates='approvals')


class AttendanceLock(TimestampMixin, Base):
    __tablename__ = 'attendance_locks'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    locked_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='locked')


class ShiftAssignment(TimestampMixin, Base):
    __tablename__ = 'shift_assignments'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    employee_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    recurrence_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='planned')


class GeofenceRule(TimestampMixin, Base):
    __tablename__ = 'geofence_rules'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Numeric(10,7))
    longitude: Mapped[float] = mapped_column(Numeric(10,7))
    radius_meters: Mapped[int] = mapped_column(Integer, default=200)
    ip_restrictions: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class HolidayCalendar(TimestampMixin, Base):
    __tablename__ = 'holiday_calendar'
    __table_args__ = (UniqueConstraint('company_id', 'holiday_date', 'name', name='uq_holiday_company_date_name'),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    state_code: Mapped[str] = mapped_column(String(20), default='DE-BE')
    holiday_date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(20), default='public')


class NotificationEvent(TimestampMixin, Base):
    __tablename__ = 'notification_events'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    type: Mapped[str] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(20), default='email')
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='queued')


class OfflineSyncEvent(TimestampMixin, Base):
    __tablename__ = 'offline_sync_events'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')


class AttendanceExportJob(TimestampMixin, Base):
    __tablename__ = 'attendance_export_jobs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    format: Mapped[str] = mapped_column(String(20))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    output_path: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AttendanceSourceEvent(TimestampMixin, Base):
    __tablename__ = 'attendance_source_events'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    attendance_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('attendance_entries.id'), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10,7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10,7), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column('metadata', JSON, nullable=True)
    entry: Mapped['AttendanceEntry | None'] = relationship(back_populates='source_events')


class KioskDevice(TimestampMixin, Base):
    __tablename__ = 'kiosk_devices'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    unique_code: Mapped[str] = mapped_column(String(100), unique=True)
    pin_required: Mapped[bool] = mapped_column(Boolean, default=True)
    qr_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    employee_number_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    restricted_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_logout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    allowed_ip_ranges: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='active')


class AuditLog(TimestampMixin, Base):
    __tablename__ = 'audit_logs'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(255))
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column('metadata', JSON, nullable=True)
