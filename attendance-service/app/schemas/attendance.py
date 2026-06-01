from datetime import datetime, date
from uuid import UUID
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class BreakOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    attendance_entry_id: UUID
    start_at: datetime
    end_at: datetime | None = None
    duration_minutes: int
    source: str


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    attendance_entry_id: UUID
    flag_type: str
    severity: str
    message: str


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    attendance_entry_id: UUID
    level: int
    approver_user_id: UUID | None = None
    status: str
    decision_reason: str | None = None


class SourceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    attendance_entry_id: UUID | None = None
    user_id: UUID | None = None
    source: str
    ip_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    metadata_json: dict | None = None


class AttendanceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    user_id: UUID
    employee_code: str | None = None
    branch_id: UUID | None = None
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    source: str
    status: str
    date: date
    worked_minutes: int
    target_work_minutes: int | None = None
    break_minutes: int
    overtime_minutes: int
    late_minutes: int
    early_departure_minutes: int
    absence_type: str | None = None
    manual_reason: str | None = None
    notes: str | None = None
    breaks: list[BreakOut] = []
    flags: list[FlagOut] = []
    approvals: list[ApprovalOut] = []
    source_events: list[SourceEventOut] = []


class CheckInIn(BaseModel):
    employee_code: str | None = None
    branch_id: UUID | None = None
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    source: str = 'web'
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None
    check_in_at: datetime | None = None


class CheckOutIn(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    check_out_at: datetime | None = None


class StartBreakIn(BaseModel):
    source: str = 'web'
    start_at: datetime | None = None


class EndBreakIn(BaseModel):
    end_at: datetime | None = None


class ManualEntryIn(BaseModel):
    user_id: UUID | None = None
    employee_code: str | None = None
    branch_id: UUID | None = None
    check_in_at: datetime
    check_out_at: datetime
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    reason: str
    break_minutes: int = Field(default=0, ge=0)
    notes: str | None = None


class CorrectionRequestIn(BaseModel):
    attendance_entry_id: UUID
    correction_type: str | None = Field(default=None, max_length=80)
    reason: str
    requested_check_in_at: datetime | None = None
    requested_check_out_at: datetime | None = None
    requested_break_minutes: int | None = Field(default=None, ge=0)
    requester_timezone: str | None = Field(default=None, max_length=100)


class CorrectionReviewIn(BaseModel):
    correction_request_id: UUID
    status: Literal['approved', 'rejected']
    decision_reason: str | None = None


class BulkCorrectionReviewIn(BaseModel):
    ids: list[UUID]
    status: Literal['approved', 'rejected']
    decision_reason: str | None = None


class SubmissionReviewIn(BaseModel):
    attendance_entry_id: UUID
    status: Literal['approved', 'rejected']
    decision_reason: str | None = None


class LockPeriodIn(BaseModel):
    from_date: date
    to_date: date
    reason: str | None = None


class UnlockPeriodIn(BaseModel):
    lock_id: UUID


class ResetSelfDateIn(BaseModel):
    target_date: date


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    timezone: str
    daily_target_hours: float
    weekly_hours: float
    max_daily_hours: float
    max_weekly_average_hours: float
    break_after_6h_minutes: int
    break_after_9h_minutes: int
    rest_period_hours: int
    late_grace_minutes: int
    auto_insert_breaks: bool
    sunday_justification_required: bool
    require_geofence_on_mobile: bool
    lock_after_days: int
    payroll_round_to_minutes: int
    daily_grace_early_departure_minutes: int
    federal_state: str


class PolicyUpdateIn(BaseModel):
    timezone: str | None = None
    daily_target_hours: float | None = None
    weekly_hours: float | None = None
    max_daily_hours: float | None = None
    max_weekly_average_hours: float | None = None
    break_after_6h_minutes: int | None = None
    break_after_9h_minutes: int | None = None
    rest_period_hours: int | None = None
    late_grace_minutes: int | None = None
    auto_insert_breaks: bool | None = None
    sunday_justification_required: bool | None = None
    require_geofence_on_mobile: bool | None = None
    lock_after_days: int | None = None
    payroll_round_to_minutes: int | None = None
    daily_grace_early_departure_minutes: int | None = None
    federal_state: str | None = None


class HolidayIn(BaseModel):
    state_code: str = ''
    holiday_date: date
    name: str
    category: Literal['public', 'company'] = 'public'


class HolidayImportIn(BaseModel):
    country_code: str = 'DE'
    state_code: str
    year: int


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    state_code: str
    holiday_date: date
    name: str
    category: str


class GeofenceIn(BaseModel):
    branch_id: UUID | None = None
    name: str
    latitude: float
    longitude: float
    radius_meters: int = 200
    ip_restrictions: dict | list | None = None
    is_active: bool = True


class GeofenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None = None
    name: str
    latitude: float
    longitude: float
    radius_meters: int
    ip_restrictions: dict | list | None = None
    is_active: bool


class ShiftIn(BaseModel):
    user_id: UUID
    employee_code: str | None = None
    branch_id: UUID | None = None
    name: str
    start_at: datetime
    end_at: datetime
    break_minutes: int = 0
    recurrence_rule: str | None = None
    status: str = 'planned'


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    user_id: UUID
    employee_code: str | None = None
    branch_id: UUID | None = None
    name: str
    start_at: datetime
    end_at: datetime
    break_minutes: int
    recurrence_rule: str | None = None
    status: str


class KioskDeviceIn(BaseModel):
    branch_id: UUID | None = None
    name: str
    unique_code: str
    pin_required: bool = True
    qr_enabled: bool = False
    employee_number_enabled: bool = True
    restricted_mode: bool = True
    auto_logout_seconds: int = 30
    allowed_ip_ranges: dict | list | None = None
    status: str = 'active'


class KioskDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None = None
    name: str
    unique_code: str
    pin_required: bool
    qr_enabled: bool
    employee_number_enabled: bool
    restricted_mode: bool
    auto_logout_seconds: int
    allowed_ip_ranges: dict | list | None = None
    status: str


class KioskCheckInIn(BaseModel):
    user_id: UUID
    employee_code: str | None = None
    branch_id: UUID | None = None
    kiosk_device_id: UUID | None = None
    notes: str | None = None


class OfflineSyncIn(BaseModel):
    source: Literal['mobile', 'kiosk']
    payload: dict[str, Any]


class ExportJobIn(BaseModel):
    format: Literal['csv', 'excel', 'datev', 'lexware', 'pdf']
    from_date: date
    to_date: date
    filters: dict[str, Any] | None = None


class ExportCompleteIn(BaseModel):
    job_id: UUID


class ExportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    requested_by_user_id: UUID
    format: str
    from_date: date
    to_date: date
    filters: dict | None = None
    status: str
    output_path: str | None = None


class NotificationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    user_id: UUID | None = None
    type: str
    channel: str
    payload: dict
    status: str


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    attendance_entry_id: UUID
    company_id: UUID
    requested_by_user_id: UUID
    correction_type: str | None = None
    requester_timezone: str | None = None
    reason: str
    requested_check_in_at: datetime | None = None
    requested_check_out_at: datetime | None = None
    requested_break_minutes: int | None = None
    original_check_in_at: datetime | None = None
    original_check_out_at: datetime | None = None
    original_break_minutes: int | None = None
    entry_date: date | None = None
    status: str
    decision_reason: str | None = None
    reviewed_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class LockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    from_date: date
    to_date: date
    locked_by_user_id: UUID
    reason: str | None = None
    status: str
