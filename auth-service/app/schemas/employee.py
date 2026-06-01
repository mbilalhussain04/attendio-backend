from uuid import UUID
from datetime import date
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class EmployeeFieldsMixin(BaseModel):
    phone: str | None = None
    country: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    @field_validator('start_date', 'end_date')
    @classmethod
    def valid_date(cls, value: str | None):
        if value is None:
            return value
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('must use YYYY-MM-DD') from exc
        return value

    @model_validator(mode='after')
    def valid_date_range(self):
        if self.start_date and self.end_date and date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date):
            raise ValueError('end_date must be after start_date')
        if getattr(self, 'contract_type', None) in {'fixed_term_full_time', 'fixed_term_part_time', 'intern', 'working_student', 'temporary', 'contractor'} and not self.end_date:
            raise ValueError('end_date is required for limited contracts')
        return self


class EmployeeCreateRequest(EmployeeFieldsMixin):
    employee_code: str | None = None
    external_employee_id: str | None = None
    payroll_employee_id: str | None = None
    first_name: str
    last_name: str
    email: EmailStr
    job_title: str | None = None
    department: str | None = None
    manager_id: str | None = None
    branch_id: str | None = None
    project_ids: list[str] = []
    contract_type: str | None = None
    employment_type: str | None = None
    expected_hours_period: str = Field(default='weekly', pattern='^(weekly|monthly)$')
    expected_hours: float | None = Field(default=None, ge=0, le=220)
    weekly_hours: float | None = Field(default=None, ge=0, le=48)
    monthly_hours: float | None = Field(default=None, ge=0, le=220)
    city: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=64)
    role_key: str = 'employee'
    provider: str = 'local'

    @field_validator('first_name', 'last_name')
    @classmethod
    def non_blank_name(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError('must not be blank')
        return value


class BulkEmployeeCreateRequest(BaseModel):
    users: list[EmployeeCreateRequest]


class EmployeeUpdateRequest(EmployeeFieldsMixin):
    employee_code: str | None = None
    external_employee_id: str | None = None
    payroll_employee_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    job_title: str | None = None
    department: str | None = None
    manager_id: str | None = None
    branch_id: str | None = None
    project_ids: list[str] | None = None
    contract_type: str | None = None
    employment_type: str | None = None
    expected_hours_period: str | None = Field(default=None, pattern='^(weekly|monthly)$')
    expected_hours: float | None = Field(default=None, ge=0, le=220)
    weekly_hours: float | None = Field(default=None, ge=0, le=48)
    monthly_hours: float | None = Field(default=None, ge=0, le=220)
    city: str | None = None
    role_key: str | None = None
    status: str | None = Field(default=None, pattern='^(active|inactive|invited|locked)$')


class EmployeeStatusRequest(BaseModel):
    status: str = Field(pattern='^(active|inactive)$')


class RoleCreateRequest(BaseModel):
    key: str
    name: str
    description: str | None = None
    permission_keys: list[str] = []


class RoleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_keys: list[str] | None = None


class UserRoleAssignmentRequest(BaseModel):
    role_keys: list[str]


class UserPermissionOverrideRequest(BaseModel):
    allow: list[str] = []
    deny: list[str] = []


class BranchRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=100)
    status: str = Field(default='active', pattern='^(active|inactive)$')


class CompanySettingsRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    legal_name: str | None = Field(default=None, max_length=180)
    logo_url: str | None = None
    company_size: str | None = Field(default=None, max_length=40)
    industry: str | None = Field(default=None, max_length=120)
    registration_number: str | None = Field(default=None, max_length=80)
    vat_id: str | None = Field(default=None, max_length=80)
    address_line: str | None = Field(default=None, max_length=220)
    country: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=20)
    operating_model: str | None = Field(default=None, max_length=80)
    onboarding_completed: bool | None = None
    enabled_modules: list[str] | None = None
    terminology: dict[str, str] | None = None
    integrations: dict[str, dict] | None = None


class ProjectRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=2, max_length=140)
    code: str | None = Field(default=None, max_length=40)
    client: str | None = Field(default=None, max_length=140)
    branch_id: str | None = None
    status: str = Field(default='active', pattern='^(active|paused|completed|inactive)$')
    start_date: str | None = None
    end_date: str | None = None

    @field_validator('start_date', 'end_date')
    @classmethod
    def valid_project_date(cls, value: str | None):
        if value is None:
            return value
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('must use YYYY-MM-DD') from exc
        return value

    @model_validator(mode='after')
    def valid_project_date_range(self):
        if self.start_date and self.end_date and date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date):
            raise ValueError('end_date must be after start_date')
        return self


class IdPath(BaseModel):
    user_id: UUID
