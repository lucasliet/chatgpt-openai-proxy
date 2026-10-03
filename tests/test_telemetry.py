import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
import respx
from conftest import create_api_key, create_user_with_credentials
from httpx import HTTPStatusError, Response
from sqlmodel import Session, select

from app.database import get_engine
from app.models import User, utcnow
from app.pricing import CATALOG_URL, estimate_cost, refresh_prices
from app.telemetry import purge_expired, record_usage, tracked_events
from app.telemetry_models import PriceCatalog, UsageBucket

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"


def seed_prices(model="gpt-6-sol", input_price=2):
    with Session(get_engine()) as session:
        session.merge(
            PriceCatalog(
                fetched_at=utcnow(),
                prices_json=json.dumps(
                    {model: {"input": input_price, "output": 10, "cache_read": 0.2}}
                ),
            )
        )
        session.commit()


def buckets():
    with Session(get_engine()) as session:
        return list(session.exec(select(UsageBucket)).all())


@pytest.mark.parametrize(
    "path,stream",
    [
        (path, stream)
        for path in ("/v1/responses", "/v1/chat/completions", "/v1/messages")
        for stream in (False, True)
    ],
)
@respx.mock
def test_should_record_once_before_conversion(client, auth_headers, path, stream):
    seed_prices()
    completion = {
        "type": "response.completed",
        "response": {
            "id": "resp_test",
            "model": "gpt-6-sol",
            "output": [],
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 40},
                "output_tokens": 20,
                "output_tokens_details": {"reasoning_tokens": 10},
            },
        },
    }
    respx.post(CODEX_URL).mock(
        return_value=Response(200, text=f"data: {json.dumps(completion)}\n\n")
    )
    response = client.post(
        path,
        headers=auth_headers,
        json={
            "model": "claude-sonnet-4-5" if path.endswith("messages") else "gpt-6-sol",
            "input": "private prompt",
            "messages": [{"role": "user", "content": "private prompt"}],
            "stream": stream,
            "max_tokens": 50,
        },
    )
    assert response.status_code == 200
    recorded = buckets()
    assert len(recorded) == 1
    usage = recorded[0]
    assert usage.model == "gpt-6-sol"
    assert usage.calls == usage.completed == 1
    assert (usage.input_tokens, usage.cached_tokens, usage.output_tokens) == (
        100,
        40,
        20,
    )
    assert usage.cost_usd == Decimal("0.000328")
    assert usage.unknown_usage == usage.unpriced == 0
    assert "private prompt" not in usage.model_dump_json()


@respx.mock
def test_should_count_failure_without_inventing_usage(client, auth_headers):
    respx.post(CODEX_URL).mock(return_value=Response(429, text="private upstream error"))
    response = client.post(
        "/v1/responses",
        headers=auth_headers,
        json={"model": "gpt-6-terra", "input": "secret"},
    )
    assert response.status_code == 429
    usage = buckets()[0]
    assert usage.failed == usage.unknown_usage == usage.unpriced == 1
    assert usage.input_tokens == usage.output_tokens == 0


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": 10},
        {"input_tokens": True, "output_tokens": 5},
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "input_tokens_details": {"cached_tokens": 20},
        },
    ],
)
def test_should_mark_missing_or_invalid_usage_as_unknown(client, usage):
    user_id = create_user_with_credentials(client, "alice")
    seed_prices()
    record_usage(user_id, "gpt-6-sol", "completed", usage)
    recorded = buckets()[0]
    assert recorded.calls == recorded.completed == recorded.unknown_usage == recorded.unpriced == 1
    assert recorded.input_tokens == recorded.output_tokens == recorded.cached_tokens == 0


@respx.mock
def test_should_not_count_model_listing(client, auth_headers):
    respx.get("https://chatgpt.com/backend-api/codex/models").mock(
        return_value=Response(200, json={"models": ["gpt-6-sol"]})
    )
    assert client.get("/v1/models", headers=auth_headers).status_code == 200
    assert buckets() == []


def test_should_not_count_pages_or_unauthenticated_requests(client):
    client.get("/")
    client.get("/health")
    client.post("/v1/responses", json={"model": "gpt-6-sol"})
    assert buckets() == []


def test_should_preserve_historical_cost(client):
    user_id = create_user_with_credentials(client, "alice")
    seed_prices()
    record_usage(
        user_id,
        "gpt-6-sol",
        "completed",
        {"input_tokens": 1_000_000, "output_tokens": 0},
    )
    seed_prices(input_price=3)
    record_usage(
        user_id,
        "gpt-6-sol",
        "completed",
        {"input_tokens": 1_000_000, "output_tokens": 0},
    )
    assert buckets()[0].cost_usd == Decimal(5)
    assert buckets()[0].calls == 2


def test_should_increment_atomically(client):
    user_id = create_user_with_credentials(client, "alice")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda _: record_usage(
                    user_id,
                    "unknown",
                    "completed",
                    {"input_tokens": 10, "output_tokens": 5},
                ),
                range(20),
            )
        )
    assert buckets()[0].calls == 20
    assert buckets()[0].input_tokens == 200
    assert buckets()[0].unpriced == 20


@pytest.mark.parametrize("method", ["logout", "admin"])
def test_should_delete_all_telemetry_and_reject_late_writes(client, method):
    user_id = create_user_with_credentials(client, "alice")
    key = create_api_key(client, user_id)
    record_usage(user_id, "gpt-6-sol", "completed", None)
    if method == "logout":
        response = client.post("/logout", headers={"Authorization": f"Bearer {key}"})
    else:
        response = client.delete(
            f"/admin/users/{user_id}", headers={"X-Admin-Key": "sk-admin-test"}
        )
    assert response.status_code in (200, 204)
    assert buckets() == []
    record_usage(user_id, "gpt-6-sol", "completed", None)
    assert buckets() == []


def test_should_not_attribute_old_stream_to_recreated_account(client):
    user_id = create_user_with_credentials(client, "alice", account_id="old-account")
    with Session(get_engine()) as session:
        created_at = session.get(User, user_id).created_at
    client.delete(f"/admin/users/{user_id}", headers={"X-Admin-Key": "sk-admin-test"})
    new_id = create_user_with_credentials(client, "bob", account_id="new-account")
    assert new_id == user_id
    record_usage(user_id, "gpt-6-sol", "completed", None, created_at)
    assert buckets() == []


def test_should_purge_expired_hourly_buckets(client):
    user_id = create_user_with_credentials(client, "alice")
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    with Session(get_engine()) as session:
        session.add(UsageBucket(user_id=user_id, hour=now - timedelta(days=31), model="old"))
        session.add(UsageBucket(user_id=user_id, hour=now, model="new"))
        session.commit()
    purge_expired()
    assert [bucket.model for bucket in buckets()] == ["new"]


@pytest.mark.parametrize(
    "prices,input_tokens,cached,expected",
    [
        ({"input": 2, "output": 10, "cache_read": 0.2}, 100, 40, Decimal("0.000328")),
        ({"input": 2, "output": 10}, 100, 40, None),
        ({"input": 2, "output": 10}, 100, 0, Decimal("0.0004")),
        ({"input": -2, "output": 10}, 100, 0, None),
        ({"input": "NaN", "output": 10}, 100, 0, None),
        (
            {
                "input": 2,
                "output": 10,
                "tiers": [
                    {
                        "input": 4,
                        "output": 15,
                        "tier": {"type": "context", "size": 272000},
                    }
                ],
            },
            300000,
            0,
            Decimal("1.2003"),
        ),
    ],
)
def test_should_estimate_prices_and_context_tiers(prices, input_tokens, cached, expected):
    assert estimate_cost(prices, input_tokens, cached, 20) == expected


@respx.mock
async def test_should_fetch_catalog_once_and_persist(client):
    route = respx.get(CATALOG_URL).mock(
        return_value=Response(
            200,
            json={"openai": {"models": {"gpt-6-sol": {"cost": {"input": 2, "output": 10}}}}},
        )
    )
    await refresh_prices()
    await refresh_prices()
    assert route.call_count == 1
    with Session(get_engine()) as session:
        assert "gpt-6-sol" in session.get(PriceCatalog, 1).prices_json


@respx.mock
async def test_should_retain_catalog_on_outage(client):
    seed_prices()
    with Session(get_engine()) as session:
        catalog = session.get(PriceCatalog, 1)
        catalog.fetched_at = utcnow() - timedelta(days=2)
        session.add(catalog)
        session.commit()
    respx.get(CATALOG_URL).mock(return_value=Response(503))
    with pytest.raises(HTTPStatusError):
        await refresh_prices()
    with Session(get_engine()) as session:
        assert json.loads(session.get(PriceCatalog, 1).prices_json)["gpt-6-sol"]["input"] == 2


class InterruptingEngine:
    async def responses_stream(self, credentials, payload):
        yield {"type": "response.created"}
        await asyncio.sleep(60)


async def test_should_count_closed_stream_as_interrupted(client):
    user_id = create_user_with_credentials(client, "alice")
    events = tracked_events(InterruptingEngine(), None, {"model": "gpt-6-sol"}, user_id)
    await anext(events)
    await events.aclose()
    assert buckets()[0].interrupted == 1


class CreatedThenInterruptedEngine:
    async def responses_stream(self, credentials, payload):
        yield {"type": "response.created", "response": {"model": "gpt-6-sol-actual"}}
        await asyncio.sleep(60)


async def test_should_use_model_from_created_event_when_interrupted(client):
    user_id = create_user_with_credentials(client, "alice")
    events = tracked_events(CreatedThenInterruptedEngine(), None, {"model": "gpt-6-sol"}, user_id)
    await anext(events)
    await events.aclose()
    assert [(b.model, b.interrupted) for b in buckets()] == [("gpt-6-sol-actual", 1)]


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        {"openai": {"models": {"gpt-6-sol": {"cost": {"input": -1, "output": 10}}}}},
        {"openai": {"models": {"gpt-6-sol": {"cost": {"input": "NaN", "output": 1}}}}},
        {"openai": {"models": {"gpt-6-sol": {"cost": {"input": 2}}}}},
        {"openai": {"models": []}},
        {"openai": {}},
    ],
)
async def test_should_retain_catalog_when_payload_is_malformed(client, body):
    seed_prices()
    with Session(get_engine()) as session:
        catalog = session.get(PriceCatalog, 1)
        catalog.fetched_at = utcnow() - timedelta(days=2)
        session.add(catalog)
        session.commit()
    respx.get(CATALOG_URL).mock(return_value=Response(200, json=body))
    with pytest.raises((ValueError, KeyError, TypeError)):
        await refresh_prices()
    with Session(get_engine()) as session:
        stored = json.loads(session.get(PriceCatalog, 1).prices_json)
    assert stored["gpt-6-sol"]["input"] == 2


@respx.mock
async def test_should_persist_only_valid_prices(client):
    respx.get(CATALOG_URL).mock(
        return_value=Response(
            200,
            json={
                "openai": {
                    "models": {
                        "good": {"cost": {"input": 2, "output": 10}},
                        "bad": {"cost": {"input": -1, "output": 10}},
                        "none": {},
                    }
                }
            },
        )
    )
    await refresh_prices()
    with Session(get_engine()) as session:
        assert list(json.loads(session.get(PriceCatalog, 1).prices_json)) == ["good"]


def test_should_require_admin_for_usage_page(client):
    user_id = create_user_with_credentials(client, "alice")
    url = f"/backoffice/users/{user_id}/usage"
    assert client.get(url, follow_redirects=False).status_code == 303
    client.post("/admin-login", data={"key": "sk-admin-test"})
    assert client.get(url).status_code == 200
    assert client.get(url + "?days=99").status_code == 422
    for days in (1, 7, 30):
        response = client.get(f"{url}?days={days}")
        assert response.status_code == 200
        assert f'href="{url}?days={days}" aria-current=page' in response.text


def test_should_disclose_telemetry_retention_and_self_service_access(client):
    page = client.get("/").text
    assert "Telemetria de uso por usuário" in page
    assert "até 30 dias" in page
    assert 'href="/dashboard"' in page
    assert "não uma cobrança da assinatura ChatGPT" in page
    assert "sem enviar dados de usuários ou conversas ao models.dev" in page
