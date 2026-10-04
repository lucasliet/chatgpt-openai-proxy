from datetime import datetime

from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    FiniteFloat,
    StrictBool,
    StrictInt,
    field_validator,
)


class LimitWindow(BaseModel):
    used_percent: FiniteFloat = Field(ge=0, le=101)
    limit_window_seconds: int = Field(gt=0, le=366 * 86400)
    reset_at: int | None = Field(default=None, ge=0, le=253402300799)
    reset_after_seconds: int | None = Field(default=None, ge=0, le=366 * 86400)

    @field_validator(
        "used_percent", "limit_window_seconds", "reset_at", "reset_after_seconds", mode="before"
    )
    @classmethod
    def reject_boolean_counters(cls, value):
        if isinstance(value, bool):
            raise ValueError("A usage counter cannot be a boolean")
        return value


class RateLimit(BaseModel):
    allowed: StrictBool | None = None
    limit_reached: StrictBool | None = None
    primary_window: LimitWindow | None = None
    secondary_window: LimitWindow | None = None


class NamedLimit(BaseModel):
    limit_name: str | None = Field(default=None, max_length=200)
    metered_feature: str | None = Field(default=None, max_length=200)
    rate_limit: RateLimit | None = None


class Credits(BaseModel):
    balance: FiniteFloat | None = Field(default=None, ge=0)
    has_credits: StrictBool | None = None
    unlimited: StrictBool | None = None


class ResetCredits(BaseModel):
    available_count: StrictInt | None = Field(default=None, ge=0)


class ModelAvailability(BaseModel):
    available: StrictBool | None = None
    available_at: AwareDatetime | None = None


class SubscriptionUsage(BaseModel):
    plan_type: str | None = Field(default=None, max_length=80)
    rate_limit: RateLimit | None = None
    code_review_rate_limit: RateLimit | None = None
    credits: Credits | None = None
    rate_limit_reset_credits: ResetCredits | None = None
    additional_rate_limits: list[NamedLimit] | None = None
    model_usage: dict[str, ModelAvailability] | None = None


class SubscriptionResult(BaseModel):
    available: bool
    fetched_at: datetime
    usage: SubscriptionUsage | None = None
    error: str | None = None
