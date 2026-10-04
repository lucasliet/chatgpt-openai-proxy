import asyncio
import json
import time
from collections import OrderedDict

import httpx
from pydantic import TypeAdapter, ValidationError
from sqlmodel import Session

from .config import Settings
from .credentials import get_valid_user_credentials
from .models import User, utcnow
from .oauth import Credentials
from .subscription_models import (
    Credits,
    LimitWindow,
    ModelAvailability,
    NamedLimit,
    RateLimit,
    ResetCredits,
    SubscriptionResult,
    SubscriptionUsage,
)

CACHE_SECONDS = 60
FAILURE_CACHE_SECONDS = 10
MAX_CACHE_ENTRIES = 256
MAX_RESPONSE_BYTES = 1024 * 1024
type SubscriptionIdentity = tuple[int | None, str, str | None]


_rate_limit_adapter = TypeAdapter(RateLimit)
_window_adapter = TypeAdapter(LimitWindow)
_credits_adapter = TypeAdapter(Credits)
_reset_credits_adapter = TypeAdapter(ResetCredits)
_named_limit_adapter = TypeAdapter(NamedLimit)
_model_availability_adapter = TypeAdapter(ModelAvailability)


def _lenient(adapter: TypeAdapter, value: object):
    if value is None:
        return None
    try:
        return adapter.validate_python(value)
    except ValidationError:
        return None


def _principal_rate_limit(value: object) -> RateLimit | None:
    if value is None:
        return None
    try:
        return _rate_limit_adapter.validate_python(value)
    except ValidationError:
        pass
    if isinstance(value, dict):
        try:
            return _rate_limit_adapter.validate_python({**value, "secondary_window": None})
        except ValidationError:
            pass
    raise ValueError("Invalid principal rate_limit")


def _lenient_rate_limit(value: object) -> RateLimit | None:
    if value is None:
        return None
    try:
        return _rate_limit_adapter.validate_python(value)
    except ValidationError:
        pass
    if isinstance(value, dict):
        try:
            return _rate_limit_adapter.validate_python({**value, "secondary_window": None})
        except ValidationError:
            return None
    return None


def _named_limits(value: object) -> list[NamedLimit] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    valid = []
    for item in value:
        if isinstance(item, dict) and "rate_limit" in item:
            item = {**item, "rate_limit": _lenient_rate_limit(item.get("rate_limit"))}
        limit = _lenient(_named_limit_adapter, item)
        if limit is not None:
            valid.append(limit)
    return valid or None


def _model_usage(value: object) -> dict[str, ModelAvailability] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    valid = {
        name: availability
        for name, availability in (
            (name, _lenient(_model_availability_adapter, item)) for name, item in value.items()
        )
        if isinstance(name, str) and availability is not None
    }
    return valid or None


def _plan_type(value: object) -> str | None:
    if isinstance(value, str) and len(value) <= 80:
        return value
    return None


async def fetch_subscription(settings: Settings, credentials: Credentials) -> SubscriptionUsage:
    headers = {
        "Authorization": f"Bearer {credentials.access_token}",
        "ChatGPT-Account-Id": credentials.account_id,
        "User-Agent": "codex-cli",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        async with client.stream("GET", settings.codex_usage_url, headers=headers) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ValueError("Usage response exceeds size limit")
    try:
        raw = json.loads(content)
    except ValueError as exc:
        raise ValueError("Usage response is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("Usage response is not an object")
    usage = SubscriptionUsage(
        plan_type=_plan_type(raw.get("plan_type")),
        rate_limit=_principal_rate_limit(raw.get("rate_limit")),
        code_review_rate_limit=_lenient_rate_limit(raw.get("code_review_rate_limit")),
        credits=_lenient(_credits_adapter, raw.get("credits")),
        rate_limit_reset_credits=_lenient(
            _reset_credits_adapter, raw.get("rate_limit_reset_credits")
        ),
        additional_rate_limits=_named_limits(raw.get("additional_rate_limits")),
        model_usage=_model_usage(raw.get("model_usage")),
    )
    if not any(
        (
            usage.rate_limit,
            usage.code_review_rate_limit,
            usage.credits,
            usage.rate_limit_reset_credits,
            usage.additional_rate_limits,
            usage.model_usage,
        )
    ):
        raise ValueError("Usage response contains no subscription limits")
    return usage


class SubscriptionService:
    """Bounded, ephemeral cache per replica; never stores OAuth tokens or raw responses."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._clock = time.monotonic
        self._cache: OrderedDict[SubscriptionIdentity, tuple[float, SubscriptionResult]] = (
            OrderedDict()
        )
        self._locks: dict[SubscriptionIdentity, asyncio.Lock] = {}

    def _is_fresh(self, identity: SubscriptionIdentity) -> SubscriptionResult | None:
        cached = self._cache.get(identity)
        if cached and cached[0] > self._clock():
            self._cache.move_to_end(identity)
            return cached[1].model_copy(deep=True)
        return None

    def _store(self, identity: SubscriptionIdentity, result: SubscriptionResult) -> None:
        if not result.available and result.error == "credentials_unavailable":
            return
        ttl = CACHE_SECONDS if result.available else FAILURE_CACHE_SECONDS
        self._cache[identity] = (self._clock() + ttl, result)
        self._cache.move_to_end(identity)
        while len(self._cache) > MAX_CACHE_ENTRIES:
            self._cache.popitem(last=False)

    async def get(self, user: User, session: Session) -> SubscriptionResult:
        identity = (user.id, user.created_at.isoformat(), user.account_id)
        if (hit := self._is_fresh(identity)) is not None:
            return hit
        lock = self._locks.setdefault(identity, asyncio.Lock())
        async with lock:
            try:
                if (hit := self._is_fresh(identity)) is not None:
                    return hit
                result = await self._load(user, session)
                self._store(identity, result)
                return result.model_copy(deep=True)
            finally:
                if self._locks.get(identity) is lock:
                    self._locks.pop(identity, None)

    async def _load(self, user: User, session: Session) -> SubscriptionResult:
        try:
            credentials = await get_valid_user_credentials(session, user, self.settings)
            if credentials is None:
                return SubscriptionResult(
                    available=False, fetched_at=utcnow(), error="credentials_unavailable"
                )
            usage = await asyncio.wait_for(
                fetch_subscription(self.settings, credentials), timeout=12
            )
            return SubscriptionResult(available=True, fetched_at=utcnow(), usage=usage)
        except (httpx.HTTPError, httpx.InvalidURL, ValidationError, ValueError, TimeoutError):
            return SubscriptionResult(
                available=False, fetched_at=utcnow(), error="upstream_unavailable"
            )
