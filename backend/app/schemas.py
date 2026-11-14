from datetime import datetime, time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator

FEATURES = (
    "attendance_gps",
    "field_service_tickets",
    "sales_crm",
    "amc_tracker",
    "monthly_email_reports",
    "background_location",
)
Role = Literal["COMPANY_ADMIN", "DISPATCHER", "ENGINEER", "SALES"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def trim_non_secrets(cls, value, info):
        if isinstance(value, str) and info.field_name not in ("password", "new_password"):
            return value.strip()
        return value


class Login(Strict):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    client_type: Literal["web", "native"] = "web"


class PlatformLogin(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    otp: str = Field(pattern=r"^\d{6}$")


class Refresh(Strict):
    refresh_token: str | None = Field(default=None, max_length=512)


class Forgot(Strict):
    slug: str = Field(max_length=63)
    email: EmailStr


class Reset(Strict):
    token: str = Field(max_length=512)
    new_password: str = Field(min_length=12, max_length=128)


class Branch(Strict):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=1000)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_m: int = Field(default=150, ge=25, le=5000)


class Shift(Strict):
    name: str = Field(min_length=1, max_length=100)
    start_local: time
    end_local: time
    end_day_offset: Literal[0, 1] = 0
    grace_minutes: int = Field(default=15, ge=0, le=120)
    weekdays: list[int] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def validate_schedule(self):
        if len(set(self.weekdays)) != len(self.weekdays) or any(d not in range(1, 8) for d in self.weekdays):
            raise ValueError("Unique ISO weekdays 1–7 required")
        duration = (
            self.end_local.hour * 60
            + self.end_local.minute
            + self.end_day_offset * 1440
            - self.start_local.hour * 60
            - self.start_local.minute
        )
        if not 1 <= duration <= 1440:
            raise ValueError("Shift must be between one minute and 24 hours")
        return self


class InitialAdmin(Strict):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)


class FeatureMap(Strict):
    attendance_gps: bool = False
    field_service_tickets: bool = False
    sales_crm: bool = False
    amc_tracker: bool = False
    monthly_email_reports: bool = False
    background_location: bool = False

    @model_validator(mode="after")
    def dependencies(self):
        if self.amc_tracker and not self.field_service_tickets:
            raise ValueError("AMC requires field service")
        if self.background_location and not self.attendance_gps:
            raise ValueError("Background location requires attendance")
        return self


class CreateTenant(Strict):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    timezone: str = "Asia/Kolkata"
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    max_active_employees: int = Field(ge=1, le=10000)
    storage_quota_bytes: int = Field(ge=1048576, le=10995116277760)
    valid_until: datetime
    branch: Branch
    shift: Shift
    admin: InitialAdmin
    features: FeatureMap

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown IANA timezone")
        return value

    @field_validator("valid_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone offset required")
        return value


class UpdateTenant(Strict):
    name: str = Field(min_length=1, max_length=150)
    status: Literal["ACTIVE", "SUSPENDED"]
    max_active_employees: int = Field(ge=1, le=10000)
    storage_quota_bytes: int = Field(ge=1048576, le=10995116277760)
    valid_until: datetime
    reason: str = Field(min_length=5, max_length=500)

    _aware = field_validator("valid_until")(classmethod(CreateTenant.aware.__func__))


class FeaturesUpdate(Strict):
    features: FeatureMap
    reason: str = Field(min_length=5, max_length=500)


class AdminReset(Strict):
    admin_user_id: UUID
    reason: str = Field(min_length=5, max_length=500)


class Employee(Strict):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    role: Role
    branch_id: UUID
    shift_id: UUID
    work_mode: Literal["OFFICE", "FIELD"]


class EmployeeUpdate(Strict):
    display_name: str = Field(min_length=1, max_length=100)
    role: Role
    active: bool
    work_mode: Literal["OFFICE", "FIELD"]
    reason: str = Field(min_length=5, max_length=500)


class Reason(Strict):
    reason: str = Field(min_length=5, max_length=500)
