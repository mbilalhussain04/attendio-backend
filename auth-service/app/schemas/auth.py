from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator


class BootstrapCompanyRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=150)
    owner_first_name: str = Field(max_length=80)
    owner_last_name: str = Field(max_length=80)
    owner_email: EmailStr
    owner_password: str = Field(min_length=8, max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_token: str | None = None
    tenant_slug: str | None = Field(default=None, max_length=120)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class SsoDiscoverRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=64)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=8, max_length=64)
    new_password: str = Field(min_length=12, max_length=64)
    revoke_other_sessions: bool = False

    @field_validator('new_password')
    @classmethod
    def strong_new_password(cls, value: str):
        checks = (
            any(char.isupper() for char in value),
            any(char.islower() for char in value),
            any(char.isdigit() for char in value),
            any(not char.isalnum() for char in value),
        )
        if not all(checks):
            raise ValueError('new_password must include uppercase, lowercase, number, and special character')
        return value


class VerifyTokenRequest(BaseModel):
    token: str


class ResendVerificationTokenRequest(BaseModel):
    token: str


class MfaVerifyRequest(BaseModel):
    token: str = Field(min_length=6, max_length=6)


class MfaDisableRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=64)
    token: str = Field(min_length=6, max_length=32)


class MfaRecoveryCodesRegenerateRequest(BaseModel):
    token: str = Field(min_length=6, max_length=32)


class RevokeSessionRequest(BaseModel):
    session_id: UUID


class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: list[str] = []


class RevokeApiKeyRequest(BaseModel):
    api_key_id: UUID


class ImpersonateRequest(BaseModel):
    target_user_id: UUID


class ProfileUpdateRequest(BaseModel):
    profile_picture_url: str | None = Field(default=None, max_length=2048)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=20)
    notification_preferences: dict[str, bool] | None = None

    @field_validator('profile_picture_url')
    @classmethod
    def valid_profile_picture_url(cls, value: str | None):
        if value is None:
            return value
        value = value.strip()
        if not value:
            return None
        if not value.startswith(('http://', 'https://')):
            raise ValueError('profile_picture_url must use http or https')
        return value


class SecurityPolicyUpdateRequest(BaseModel):
    password_min_length: int = Field(default=12, ge=12, le=64)
    require_mfa: bool = False
    session_ttl_days: int = Field(default=7, ge=1, le=90)
    mfa_grace_period_days: int = Field(default=14, ge=0, le=90)


class MfaReminderRequest(BaseModel):
    user_ids: list[UUID] = []
    send_to_all_missing: bool = False


class KioskPinRequest(BaseModel):
    user_id: UUID
    pin: str = Field(pattern=r'^\d{4,6}$')


class KioskLoginRequest(BaseModel):
    employee_code: str
    pin: str = Field(pattern=r'^\d{4,6}$')
    tenant_slug: str | None = None
