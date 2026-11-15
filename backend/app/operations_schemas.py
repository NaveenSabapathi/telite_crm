"""Strict command DTOs. Identity, timestamps and monetary snapshots are server-owned."""

from datetime import date
from decimal import Decimal
from typing import Literal, Annotated
from uuid import UUID
from pydantic import Field, AwareDatetime, model_validator
from .schemas import Strict

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class Location(Strict):
    client_event_id: UUID
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float = Field(ge=0, le=50, allow_inf_nan=False)
    captured_at: AwareDatetime
    mock_signal: bool = False
    installation_id: UUID
    platform: Literal["web", "android"] = "web"


class Punch(Strict):
    location: Location
    work_mode: Literal["OFFICE", "FIELD"]


class Checkout(Strict):
    location: Location


class Leave(Strict):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    kind: Literal["HALF_DAY", "ON_DUTY", "SICK", "ANNUAL", "PERMISSION"]
    reason: str = Field(min_length=5, max_length=1000)

    @model_validator(mode="after")
    def interval(self):
        if self.ends_at <= self.starts_at or (self.ends_at - self.starts_at).days > 366:
            raise ValueError("Invalid leave interval")
        return self


class Decision(Strict):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=5, max_length=500)


class Assignment(Strict):
    user_id: UUID
    reason: str = Field(min_length=5, max_length=500)


class EmployeeSchedule(Strict):
    branch_id: UUID
    shift_id: UUID
    reason: str = Field(min_length=5, max_length=500)


class CustomerIntake(Strict):
    customer_name: str = Field(min_length=1, max_length=150)
    customer_phone: str = Field(min_length=5, max_length=40)
    address: str = Field(min_length=1, max_length=1000)
    site_lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    site_lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class TicketCreate(CustomerIntake):
    category: str = Field(min_length=1, max_length=80)
    brand: str = Field(max_length=100, default="")
    model: str = Field(max_length=100, default="")
    serial_number: str = Field(min_length=1, max_length=150)
    warranty_until: date | None = None
    coverage: Literal["WARRANTY", "AMC", "CHARGEABLE"] = "CHARGEABLE"
    reported_issue: str = Field(min_length=5, max_length=4000)
    estimated_cost: Money = Decimal("0")
    assigned_to: UUID | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"


class Transition(Strict):
    status: Literal["EN_ROUTE", "ON_SITE", "IN_PROGRESS", "WAITING_SPARES", "WAITING_APPROVAL", "RESOLVED"]
    note: str = Field(min_length=5, max_length=4000)
    location: Location | None = None


class Completion(Strict):
    location: Location
    resolution_notes: str = Field(min_length=5, max_length=4000)
    photo_id: UUID
    signature_id: UUID
    signer_name: str = Field(min_length=2, max_length=150)
    customer_consent: Literal[True]
    payment_mode: Literal["CASH", "UPI", "CREDIT", "WARRANTY"]
    collected_amount: Money = Decimal("0")
    payment_reference: str = Field(default="", max_length=150)


class Evidence(Strict):
    kind: Literal["AFTER", "SIGNATURE"]
    image_base64: str = Field(min_length=20, max_length=55000)


class PartLog(Strict):
    name: str = Field(min_length=1, max_length=150)
    quantity: int = Field(ge=1, le=1000)
    unit_cost: Money
    vendor_rma_status: str = Field(default="", max_length=500)
    note: str = Field(min_length=5, max_length=1000)


class LeadCreate(CustomerIntake):
    requirement: str = Field(min_length=5, max_length=4000)
    estimated_value: Money = Decimal("0")
    assigned_to: UUID | None = None
    source: Literal["WALK_IN", "PHONE", "WHATSAPP", "INDIAMART_WEB", "REFERRAL", "FIELD_VISIT"] = "PHONE"
    next_followup_at: AwareDatetime | None = None


class LeadStage(Strict):
    stage: Literal["CONTACTED", "SURVEY_DONE", "QUOTE_SENT", "NEGOTIATION", "WON", "LOST"]
    reason: str = Field(min_length=5, max_length=1000)
    won_value: Money | None = None


class Activity(Strict):
    note: str = Field(min_length=1, max_length=4000)
    next_followup_at: AwareDatetime | None = None
    location: Location | None = None


class Conversion(Strict):
    reported_issue: str = Field(min_length=5, max_length=4000)
    assigned_to: UUID | None = None


class ReportPeriod(Strict):
    month: str = Field(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")


class Consent(Strict):
    granted: bool
    policy_version: Literal["foreground-2026-11"]


class Deletion(Strict):
    password: str = Field(min_length=1, max_length=128)
