import asyncio
import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from .database import get_engine
from .models import utcnow
from .telemetry_models import PriceCatalog

logger = logging.getLogger("chatgpt-proxy.pricing")
CATALOG_URL = "https://models.dev/api.json"


class Rates(BaseModel):
    input: Decimal = Field(ge=0, allow_inf_nan=False)
    output: Decimal = Field(ge=0, allow_inf_nan=False)
    cache_read: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class ContextThreshold(BaseModel):
    type: Literal["context"]
    size: int = Field(gt=0)


class ContextRates(Rates):
    tier: ContextThreshold


class ModelPrices(Rates):
    tiers: list[ContextRates] = Field(default_factory=list)
    context_over_200k: Rates | None = None


def catalog_is_fresh() -> bool:
    with Session(get_engine()) as session:
        catalog = session.get(PriceCatalog, 1)
        return bool(catalog and catalog.fetched_at >= utcnow() - timedelta(hours=24))


def persist_catalog(prices: dict) -> None:
    with Session(get_engine()) as session:
        session.merge(PriceCatalog(fetched_at=utcnow(), prices_json=json.dumps(prices)))
        session.commit()


def valid_prices(models: dict) -> dict:
    prices = {}
    for name, model in models.items():
        cost = model.get("cost") if isinstance(model, dict) else None
        try:
            ModelPrices.model_validate(cost)
        except ValidationError:
            continue
        prices[name] = cost
    return prices


async def refresh_prices() -> None:
    if await asyncio.to_thread(catalog_is_fresh):
        return
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(CATALOG_URL)
        response.raise_for_status()
        models = response.json()["openai"]["models"]
        if not isinstance(models, dict):
            raise TypeError("models.dev OpenAI models must be an object")
    prices = valid_prices(models)
    if not prices:
        raise ValueError("models.dev OpenAI catalog contains no valid prices")
    await asyncio.to_thread(persist_catalog, prices)


async def maintain_telemetry(update_prices: bool) -> None:
    from .telemetry import purge_expired

    while True:
        try:
            await asyncio.to_thread(purge_expired)
            if update_prices:
                await refresh_prices()
        except (
            httpx.HTTPError,
            SQLAlchemyError,
            ValueError,
            KeyError,
            TypeError,
        ) as error:
            logger.warning(
                "Telemetry maintenance unavailable (%s); retaining last valid prices",
                type(error).__name__,
            )
        await asyncio.sleep(3600)


def estimate_cost(
    prices: dict, input_tokens: int, cached_tokens: int, output_tokens: int
) -> Decimal | None:
    try:
        parsed = ModelPrices.model_validate(prices)
    except ValidationError:
        return None
    selected: Rates = parsed
    matching = [tier for tier in parsed.tiers if input_tokens > tier.tier.size]
    if matching:
        selected = max(matching, key=lambda tier: tier.tier.size)
    elif not parsed.tiers and input_tokens > 200_000 and parsed.context_over_200k:
        selected = parsed.context_over_200k
    if cached_tokens and selected.cache_read is None:
        return None
    cache_price = selected.cache_read or Decimal(0)
    return (
        (input_tokens - cached_tokens) * selected.input
        + cached_tokens * cache_price
        + output_tokens * selected.output
    ) / 1_000_000
