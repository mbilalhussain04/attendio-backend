from datetime import date, time
from pydantic import BaseModel, Field, field_validator, model_validator


class ShiftTemplateRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=140)
    code: str | None = Field(default=None, max_length=40)
    start_time: time
    end_time: time
    break_minutes: int = Field(default=0, ge=0, le=720)
    timezone: str | None = Field(default=None, max_length=100)
    location_id: str | None = Field(default=None, max_length=80)
    department_id: str | None = Field(default=None, max_length=80)
    color: str | None = Field(default=None, max_length=24)
    status: str = Field(default='active', pattern='^(active|inactive)$')

    @model_validator(mode='after')
    def valid_duration(self):
        if self.start_time == self.end_time:
            raise ValueError('start_time and end_time cannot be the same')
        return self


class RosterTemplateRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=140)
    shift_template_id: str
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[int] = Field(default_factory=list)
    employee_ids: list[str] = Field(default_factory=list)
    status: str = Field(default='active', pattern='^(active|inactive)$')

    @field_validator('days_of_week')
    @classmethod
    def valid_weekdays(cls, value: list[int]):
        invalid = [day for day in value if day < 0 or day > 6]
        if invalid:
            raise ValueError('days_of_week must use values 0-6')
        return sorted(set(value))

    @model_validator(mode='after')
    def valid_date_range(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError('end_date must be after start_date')
        return self


class ScheduleAssignmentRequest(BaseModel):
    id: str | None = None
    employee_id: str
    shift_template_id: str
    subject: str | None = Field(default=None, max_length=140)
    work_date: date
    start_time: time | None = None
    end_time: time | None = None
    status: str = Field(default='scheduled', pattern='^(scheduled|published|completed|cancelled|absent|no_show|late|sick|excused)$')
    notes: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    color: str | None = Field(default=None, max_length=24)
    attendee_emails: list[str] = Field(default_factory=list)
    repeat_rule: str | None = Field(default=None, max_length=80)
    entry_kind: str | None = Field(default=None, pattern='^(shift|meeting)$')
    force: bool = False
    sync_provider: str | None = Field(default=None, pattern='^(microsoft_teams)$')
    create_online_meeting: bool = True
