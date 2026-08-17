from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


MachineHash = str


class ActivationRequest(BaseModel):
    code: str = Field(min_length=16, max_length=80)
    machine_hash: MachineHash = Field(min_length=16, max_length=128)
    install_id: str = Field(min_length=8, max_length=128)
    device_label: str | None = Field(default=None, max_length=120)
    app_version: str = Field(default="unknown", max_length=40)


class LicenseCheckRequest(BaseModel):
    license_id: str
    refresh_token: str = Field(min_length=32, max_length=256)
    machine_hash: MachineHash = Field(min_length=16, max_length=128)
    install_id: str = Field(min_length=8, max_length=128)
    app_version: str = Field(default="unknown", max_length=40)


class RenewalRequest(LicenseCheckRequest):
    code: str = Field(min_length=16, max_length=80)


class LicenseResponse(BaseModel):
    license_id: str
    status: str
    plan_type: str
    expires_at: datetime | None
    offline_until: datetime
    server_time: datetime
    device_limit: int
    refresh_token: str | None = None
    signed_receipt: str


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AdminPasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class CardGenerateRequest(BaseModel):
    plan_type: Literal["monthly", "quarterly", "yearly", "permanent", "custom"]
    duration_days: int | None = Field(default=None, ge=1, le=36500)
    count: int = Field(default=1, ge=1, le=500)
    device_limit: int = Field(default=1, ge=1, le=20)
    offline_grace_hours: int = Field(default=72, ge=0, le=720)
    channel: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_duration(self):
        if self.plan_type == "custom" and not self.duration_days:
            raise ValueError("custom plan requires duration_days")
        return self


class CardGenerateResponse(BaseModel):
    batch_id: str
    codes: list[str]
    plan_type: str
    duration_days: int | None


class LicenseActionRequest(BaseModel):
    action: Literal["extend", "disable", "enable", "set_permanent"]
    days: int | None = Field(default=None, ge=1, le=36500)
    note: str | None = Field(default=None, max_length=500)


class RebindCodeRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class RebindCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class CardStatusRequest(BaseModel):
    action: Literal["disable", "enable", "void"]
