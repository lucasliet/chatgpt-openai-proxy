from types import SimpleNamespace

import httpx
import pytest
import respx
from conftest import create_api_key, create_user_with_credentials
from sqlmodel import Session, select
from test_dashboard import authenticate

from app.database import get_engine
from app.models import ApiKey, User
from app.telemetry_models import UsageBucket

USAGE_URL = "https://usage.example.test/usage"


@pytest.fixture
def usage_upstream(client):
    client.app.state.settings.codex_usage_url = USAGE_URL
    with respx.mock as mock:
        route = mock.get(USAGE_URL).mock(return_value=httpx.Response(200, json=payload()))
        yield route


def payload(percent=23):
    return {
        "email": "private@example.test",
        "account_id": "private-id",
        "user_id": "private-user",
        "plan_type": "plus",
        "rate_limit": {
            "allowed": True,
            "limit_reached": False,
            "primary_window": {
                "used_percent": percent,
                "limit_window_seconds": 18000,
                "reset_at": 1800000000,
            },
            "secondary_window": {"used_percent": "10", "limit_window_seconds": 604800},
        },
        "credits": {"balance": "12.5", "has_credits": True, "unlimited": False, "secret": "hidden"},
        "rate_limit_reset_credits": {"available_count": 2, "credits": [{"id": "secret-reset-id"}]},
        "additional_rate_limits": None,
        "model_usage": None,
    }


def test_should_authenticate_and_filter_upstream_usage(client, auth_headers, usage_upstream):
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["available"] is True
    assert data["usage"]["rate_limit"]["primary_window"]["used_percent"] == 23
    assert data["usage"]["credits"]["balance"] == 12.5
    for private in [
        "private@example.test",
        "private-id",
        "private-user",
        "hidden",
        "secret-reset-id",
    ]:
        assert private not in response.text
    request = usage_upstream.calls[0].request
    assert request.headers["authorization"] == "Bearer at-acc-alice"
    assert request.headers["ChatGPT-Account-Id"] == "acc-alice"
    assert request.headers["User-Agent"] == "codex-cli"


def test_should_reject_unauthenticated_and_revoked_keys(client, user_key, usage_upstream):
    assert client.get("/v1/usage").status_code == 401
    with Session(get_engine()) as session:
        key = session.exec(select(ApiKey)).first()
        key.revoked_at = key.created_at
        session.add(key)
        session.commit()
    assert (
        client.get("/v1/usage", headers={"Authorization": f"Bearer {user_key}"}).status_code == 401
    )
    assert not usage_upstream.called


def test_should_cache_only_for_the_same_user(client, auth_headers, usage_upstream):
    client.get("/v1/usage", headers=auth_headers)
    client.get("/v1/usage", headers=auth_headers)
    assert usage_upstream.call_count == 1
    bob = create_user_with_credentials(client, "bob", account_id="acc-bob")
    key = create_api_key(client, bob)
    usage_upstream.mock(return_value=httpx.Response(200, json=payload(81)))
    response = client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.json()["usage"]["rate_limit"]["primary_window"]["used_percent"] == 81
    assert (
        client.get("/v1/usage", headers=auth_headers).json()["usage"]["rate_limit"][
            "primary_window"
        ]["used_percent"]
        == 23
    )


@pytest.mark.parametrize(
    "body", [{}, {"rate_limit": {"primary_window": {}}}, payload(-1), payload("NaN")]
)
def test_should_not_report_invalid_usage_as_zero(client, auth_headers, usage_upstream, body):
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["available"] is False
    assert response.json()["usage"] is None


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_should_sanitize_upstream_errors(client, auth_headers, usage_upstream, status):
    usage_upstream.mock(return_value=httpx.Response(status, text="private-token private-email"))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert "private" not in response.text


def test_should_not_require_oauth_for_cached_usage(client, auth_headers, usage_upstream):
    client.get("/v1/usage", headers=auth_headers)
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user.expires_at = 0
        session.add(user)
        session.commit()
    assert client.get("/v1/usage", headers=auth_headers).status_code == 200
    assert usage_upstream.call_count == 1


def test_should_render_limits_using_only_dashboard_identity(client, user_key, usage_upstream):
    assert client.get("/dashboard/limits", follow_redirects=False).status_code == 303
    authenticate(client, user_key)
    page = client.get("/dashboard").text
    assert "Limites da assinatura" in page
    assert 'data-url="/dashboard/limits"' in page
    assert not usage_upstream.called
    response = client.get("/dashboard/limits?user_id=999")
    assert response.status_code == 200
    assert "23% usado" in response.text
    assert "5 horas" in response.text
    assert "7 dias" in response.text
    assert "12.5" in response.text
    assert "private@example" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_should_preserve_telemetry_when_subscription_unavailable(client, user_key, usage_upstream):
    authenticate(client, user_key)
    usage_upstream.mock(side_effect=httpx.ConnectTimeout("private-secret"))
    assert "indisponíveis" in client.get("/dashboard/limits").text
    assert client.get("/dashboard").status_code == 200


def test_should_expire_cache_without_reusing_old_percentages(
    client, auth_headers, usage_upstream, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(client.app.state.subscription, "_clock", lambda: clock[0])
    client.get("/v1/usage", headers=auth_headers)
    clock[0] += 61
    usage_upstream.mock(return_value=httpx.Response(200, json=payload(41)))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.json()["usage"]["rate_limit"]["primary_window"]["used_percent"] == 41
    assert usage_upstream.call_count == 2


def test_should_discard_cache_after_account_recreation(client, auth_headers, usage_upstream):
    client.get("/v1/usage", headers=auth_headers)
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user_id = user.id
    client.delete(f"/admin/users/{user_id}", headers={"X-Admin-Key": "sk-admin-test"})
    new_id = create_user_with_credentials(client, "new-alice", account_id="acc-alice")
    key = create_api_key(client, new_id)
    usage_upstream.mock(return_value=httpx.Response(200, json=payload(72)))
    response = client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.json()["usage"]["rate_limit"]["primary_window"]["used_percent"] == 72
    assert usage_upstream.call_count == 2


def test_should_refresh_oauth_without_rotating_api_key(client, auth_headers, usage_upstream):
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user.expires_at = 0
        session.add(user)
        session.commit()
    token_route = respx.post(client.app.state.settings.oauth_token_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "renewed-token",
                "refresh_token": "renewed-refresh",
                "expires_in": 3600,
            },
        )
    )
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 200
    assert token_route.call_count == 1
    assert usage_upstream.calls[0].request.headers["authorization"] == "Bearer renewed-token"
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        assert user.access_token == "renewed-token"
        keys = session.exec(select(ApiKey)).all()
        assert len(keys) == 1
        assert keys[0].revoked_at is None
        assert session.exec(select(UsageBucket)).all() == []


def test_should_bound_cache_size(client, monkeypatch):
    from app.models import utcnow
    from app.subscription_models import SubscriptionResult

    service = client.app.state.subscription

    async def synthetic_limits(user, session):
        return SubscriptionResult(
            available=False, fetched_at=utcnow(), error="upstream_unavailable"
        )

    monkeypatch.setattr(service, "_load", synthetic_limits)

    async def populate():
        for identity in range(260):
            await service.get(User(id=identity, name="synthetic"), None)
        assert len(service._cache) == 256

    import asyncio

    asyncio.run(populate())


def test_should_render_additional_limits_and_model_availability_safely(
    client, user_key, usage_upstream
):
    body = payload()
    body["additional_rate_limits"] = [
        {
            "limit_name": "<script>limit</script>",
            "rate_limit": {
                "allowed": False,
                "primary_window": {
                    "used_percent": 101,
                    "limit_window_seconds": 3600,
                    "reset_after_seconds": 60,
                },
            },
        }
    ]
    body["model_usage"] = {
        "<script>model</script>": {"available": False, "available_at": "2026-10-03T12:00:00+03:00"}
    }
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    authenticate(client, user_key)
    response = client.get("/dashboard/limits")
    assert "<script>" not in response.text
    assert "&lt;script&gt;limit" in response.text
    assert "&lt;script&gt;model" in response.text
    assert "09:00 UTC" in response.text
    assert 'value="100"' in response.text
    assert "101% usado" in response.text


def test_should_reject_oversized_payload(client, auth_headers, usage_upstream):
    usage_upstream.mock(return_value=httpx.Response(200, content=b"x" * (1024 * 1024 + 1)))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503


def test_should_show_no_credentials_as_unavailable_without_upstream_call(
    client, auth_headers, usage_upstream
):
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user.access_token = ""
        session.add(user)
        session.commit()
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error"] == "credentials_unavailable"
    assert not usage_upstream.called


def test_should_keep_principal_limits_when_secondary_sections_are_malformed(
    client, auth_headers, usage_upstream
):
    body = payload()
    body["credits"] = {"balance": "-1"}
    body["additional_rate_limits"] = [None]
    body["model_usage"] = {"gpt": {"available": "yes"}}
    body["code_review_rate_limit"] = {"primary_window": {}}
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["usage"]["rate_limit"]["primary_window"]["used_percent"] == 23
    assert data["usage"]["credits"] is None
    assert data["usage"]["additional_rate_limits"] is None
    assert data["usage"]["model_usage"] is None


def test_should_reject_boolean_reset_count_without_hiding_principal_limits(
    client, auth_headers, usage_upstream
):
    body = payload()
    body["rate_limit_reset_credits"] = {"available_count": True}
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["usage"]["rate_limit"]["primary_window"]["used_percent"] == 23
    assert response.json()["usage"]["rate_limit_reset_credits"] is None


@pytest.mark.parametrize(
    "principal",
    [
        {"allowed": True, "primary_window": {"used_percent": 150, "limit_window_seconds": 18000}},
        {"allowed": "yes", "primary_window": {"used_percent": 10, "limit_window_seconds": 18000}},
        "not-an-object",
    ],
)
def test_should_report_unavailable_when_principal_rate_limit_is_invalid(
    client, auth_headers, usage_upstream, principal
):
    body = payload()
    body["rate_limit"] = principal
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["available"] is False


def test_should_tolerate_invalid_secondary_window(client, auth_headers, usage_upstream):
    body = payload()
    body["rate_limit"]["secondary_window"] = {"used_percent": -5, "limit_window_seconds": 604800}
    body["code_review_rate_limit"] = {
        "allowed": True,
        "primary_window": {"used_percent": 30, "limit_window_seconds": 3600},
        "secondary_window": {"used_percent": -5, "limit_window_seconds": 3600},
    }
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["usage"]["rate_limit"]["secondary_window"] is None
    assert (
        response.json()["usage"]["code_review_rate_limit"]["primary_window"]["used_percent"] == 30
    )
    assert response.json()["usage"]["code_review_rate_limit"]["secondary_window"] is None


def test_should_ignore_unknown_fields_in_realistic_payload(client, auth_headers, usage_upstream):
    body = payload()
    body["tomorrows_window"] = {"used_percent": 99}
    body["rate_limit"]["experimental_flag"] = True
    body["model_usage"] = {"gpt-6.1-sol": {"available": True, "next_field": 1}}
    usage_upstream.mock(return_value=httpx.Response(200, json=body))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 200
    assert "tomorrows_window" not in response.text
    assert "experimental_flag" not in response.text
    assert "next_field" not in response.text
    assert response.json()["usage"]["rate_limit"]["primary_window"]["used_percent"] == 23


def test_should_not_cache_credentials_unavailable(client, auth_headers, usage_upstream):
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user.access_token = ""
        session.add(user)
        session.commit()
    assert client.get("/v1/usage", headers=auth_headers).status_code == 503
    assert client.app.state.subscription._cache == {}
    assert not usage_upstream.called


def test_should_expire_failures_faster_than_success(
    client, auth_headers, usage_upstream, monkeypatch
):
    from app.subscription import FAILURE_CACHE_SECONDS

    clock = [100.0]
    monkeypatch.setattr(client.app.state.subscription, "_clock", lambda: clock[0])
    usage_upstream.mock(return_value=httpx.Response(500, text="boom"))
    assert client.get("/v1/usage", headers=auth_headers).status_code == 503
    clock[0] += FAILURE_CACHE_SECONDS + 1
    usage_upstream.mock(return_value=httpx.Response(200, json=payload(41)))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.json()["usage"]["rate_limit"]["primary_window"]["used_percent"] == 41
    assert usage_upstream.call_count == 2


def test_should_return_unavailable_on_timeout(client, auth_headers, usage_upstream, monkeypatch):
    import app.subscription as subscription

    async def too_slow(settings, credentials):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(subscription, "fetch_subscription", too_slow)
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["available"] is False
    assert response.json()["usage"] is None
    assert not usage_upstream.called


def test_should_enforce_upstream_timeout_via_wait_for(
    client, auth_headers, usage_upstream, monkeypatch
):
    import asyncio as asyncio_lib

    import app.subscription as subscription

    real_wait_for = asyncio_lib.wait_for

    async def fast_wait(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.05)

    async def slow_fetch(settings, credentials):
        await asyncio_lib.sleep(5)

    monkeypatch.setattr(asyncio_lib, "wait_for", fast_wait)
    monkeypatch.setattr(subscription, "fetch_subscription", slow_fetch)
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"
    assert not usage_upstream.called


def test_should_return_unavailable_when_oauth_refresh_fails(client, auth_headers, usage_upstream):
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user.expires_at = 0
        session.add(user)
        session.commit()
    token_route = respx.post(client.app.state.settings.oauth_token_url).mock(
        return_value=httpx.Response(500, text="private-oauth-error")
    )
    usage_upstream.mock(return_value=httpx.Response(401, text="private-upstream-detail"))
    response = client.get("/v1/usage", headers=auth_headers)
    assert response.status_code == 503
    assert token_route.call_count == 1
    assert "private" not in response.text
    with Session(get_engine()) as session:
        assert session.exec(select(ApiKey)).first().revoked_at is None


async def test_should_coalesce_concurrent_requests_into_one_upstream_call(
    client, auth_headers, usage_upstream, monkeypatch
):
    import asyncio

    from app.models import utcnow
    from app.subscription import SubscriptionService
    from app.subscription_models import SubscriptionResult

    service = SubscriptionService(client.app.state.settings)
    calls = 0

    async def slow_load(user, session):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return SubscriptionResult(
            available=False, fetched_at=utcnow(), error="upstream_unavailable"
        )

    monkeypatch.setattr(service, "_load", slow_load)
    user = SimpleNamespace(id=7, created_at=utcnow(), account_id="acc-synthetic")
    results = await asyncio.gather(*(service.get(user, None) for _ in range(20)))
    assert calls == 1
    assert all(result.error == "upstream_unavailable" for result in results)
