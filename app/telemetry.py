import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime, timedelta

import anyio
from sqlalchemy import delete, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from .codex import Engine
from .database import get_engine
from .models import User, utcnow
from .oauth import Credentials
from .pricing import estimate_cost
from .telemetry_models import PriceCatalog, UsageBucket

logger = logging.getLogger("chatgpt-proxy.telemetry")
COUNTERS = (
    "calls",
    "completed",
    "failed",
    "interrupted",
    "unknown_usage",
    "unpriced",
    "input_tokens",
    "cached_tokens",
    "output_tokens",
    "cost_usd",
)


def purge_expired() -> None:
    cutoff = (utcnow() - timedelta(days=30)).replace(minute=0, second=0, microsecond=0)
    with Session(get_engine()) as session:
        session.exec(delete(UsageBucket).where(UsageBucket.hour <= cutoff))
        session.commit()


def token_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def record_usage(
    user_id: int,
    model: str,
    outcome: str,
    usage: dict | None,
    user_created_at: datetime | None = None,
) -> None:
    engine = get_engine()
    with Session(engine) as session:
        incoming = token_count((usage or {}).get("input_tokens"))
        outgoing = token_count((usage or {}).get("output_tokens"))
        details = (usage or {}).get("input_tokens_details") or {}
        cached = token_count(details.get("cached_tokens", 0)) if isinstance(details, dict) else None
        known = (
            incoming is not None
            and outgoing is not None
            and cached is not None
            and cached <= incoming
        )
        catalog = session.get(PriceCatalog, 1)
        prices = json.loads(catalog.prices_json).get(model) if catalog else None
        cost = estimate_cost(prices, incoming, cached, outgoing) if known and prices else None
        values = {
            "user_id": user_id,
            "hour": utcnow().replace(minute=0, second=0, microsecond=0),
            "model": model,
            "calls": 1,
            "completed": int(outcome == "completed"),
            "failed": int(outcome == "failed"),
            "interrupted": int(outcome == "interrupted"),
            "unknown_usage": int(not known),
            "unpriced": int(cost is None),
            "input_tokens": incoming if known else 0,
            "cached_tokens": cached if known else 0,
            "output_tokens": outgoing if known else 0,
            "cost_usd": cost or 0,
        }
        insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
        owner = select(
            *[
                literal(value, UsageBucket.__table__.c[name].type).label(name)
                for name, value in values.items()
            ]
        ).where(User.id == user_id)
        if user_created_at is not None:
            owner = owner.where(User.created_at == user_created_at)
        statement = insert(UsageBucket).from_select(list(values), owner)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "hour", "model"],
            set_={
                name: getattr(UsageBucket, name) + getattr(statement.excluded, name)
                for name in COUNTERS
            },
        )
        session.execute(statement)
        session.commit()


async def tracked_events(
    engine: Engine,
    credentials: Credentials,
    payload: dict,
    user_id: int,
    user_created_at: datetime | None = None,
) -> AsyncIterator[dict]:
    """Persist counters before converters can stop consuming the terminal event."""
    model = payload.get("model") or "unknown"
    usage = None
    outcome = "interrupted"
    recorded = False
    try:
        async with aclosing(engine.responses_stream(credentials, payload)) as events:
            async for event in events:
                response = event.get("response")
                response = response if isinstance(response, dict) else {}
                if isinstance(response.get("model"), str) and response["model"]:
                    model = response["model"]
                if event.get("type") in {
                    "response.completed",
                    "response.failed",
                    "response.incomplete",
                }:
                    usage = (
                        response.get("usage") if isinstance(response.get("usage"), dict) else None
                    )
                    outcome = "completed" if event["type"] == "response.completed" else "failed"
                    if not recorded:
                        await persist_usage(user_id, model, outcome, usage, user_created_at)
                    recorded = True
                yield event
    except Exception:
        outcome = "failed"
        raise
    finally:
        if not recorded:
            await persist_usage(user_id, model, outcome, usage, user_created_at)


async def persist_usage(
    user_id: int,
    model: str,
    outcome: str,
    usage: dict | None,
    user_created_at: datetime | None = None,
) -> None:
    with anyio.CancelScope(shield=True):
        try:
            await anyio.to_thread.run_sync(
                record_usage, user_id, model, outcome, usage, user_created_at
            )
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as error:
            logger.warning(
                "Usage persistence failed (%s); inference response preserved",
                type(error).__name__,
            )
