from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from conftest import create_api_key, create_user_with_credentials
from httpx import Response
from sqlmodel import Session, select
from test_api import _id_token

from app.database import get_engine
from app.models import ApiKey, User
from app.routers.dashboard import COOKIE, session_signer
from app.telemetry import record_usage


def authenticate(client, account_id):
    start = client.post("/dashboard/login/start").json()
    state = parse_qs(urlsplit(start["authUrl"]).query)["state"][0]
    respx.post(client.app.state.settings.oauth_token_url).mock(
        return_value=Response(
            200,
            json={
                "access_token": "dashboard-only-token",
                "refresh_token": "dashboard-only-refresh",
                "expires_in": 3600,
                "id_token": _id_token(account_id),
            },
        )
    )
    return client.post(
        "/dashboard/login/complete",
        json={"callbackUrl": f"http://localhost:1455/auth/callback?code=code&state={state}"},
    )


@respx.mock
def test_should_authenticate_existing_user_without_changing_credentials_or_keys(client):
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    key = create_api_key(client, user_id)
    with Session(get_engine()) as session:
        original = session.get(User, user_id).model_dump()
    response = authenticate(client, "acc-alice")
    assert response.status_code == 200
    assert response.json() == {"dashboard": True}
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert client.get("/dashboard").status_code == 200
    with Session(get_engine()) as session:
        assert session.get(User, user_id).model_dump() == original
        keys = session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all()
        assert len(keys) == 1
        assert keys[0].revoked_at is None
    assert key.startswith("sk-")


@respx.mock
def test_should_not_register_unknown_account(client):
    response = authenticate(client, "unknown-account")
    assert response.status_code == 403
    assert "Nenhuma conta foi criada" in response.text
    with Session(get_engine()) as session:
        assert session.exec(select(User)).all() == []
        assert session.exec(select(ApiKey)).all() == []
    assert COOKIE not in client.cookies


@respx.mock
def test_should_isolate_usage_and_escape_user_content(client):
    alice = create_user_with_credentials(client, "<script>alice</script>", account_id="acc-alice")
    bob = create_user_with_credentials(client, "bob", account_id="acc-bob")
    record_usage(alice, "alice-model", "completed", {"input_tokens": 10, "output_tokens": 20})
    record_usage(
        bob,
        "bob-private-model",
        "completed",
        {"input_tokens": 999999, "output_tokens": 0},
    )
    authenticate(client, "acc-alice")
    response = client.get(f"/dashboard?user_id={bob}")
    assert response.status_code == 200
    assert "alice-model" in response.text
    assert "bob-private-model" not in response.text
    assert "<script>alice</script>" not in response.text
    assert "&lt;script&gt;alice&lt;/script&gt;" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/dashboard?days=99").status_code == 422


@respx.mock
@pytest.mark.parametrize("days", [1, 7, 30])
def test_should_accept_every_period_filter(client, days):
    create_user_with_credentials(client, "alice", account_id="acc-alice")
    authenticate(client, "acc-alice")
    response = client.get(f"/dashboard?days={days}")
    assert response.status_code == 200
    assert f'href="/dashboard?days={days}" aria-current=page' in response.text


@respx.mock
def test_should_logout_session_without_deleting_account(client):
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    authenticate(client, "acc-alice")
    response = client.post("/dashboard/logout", follow_redirects=False)
    assert response.status_code == 303
    assert (
        client.get("/dashboard", follow_redirects=False).headers["location"] == "/dashboard/login"
    )
    with Session(get_engine()) as session:
        assert session.get(User, user_id) is not None


@respx.mock
def test_should_invalidate_session_when_account_deleted_and_id_reused(client):
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    authenticate(client, "acc-alice")
    client.delete(f"/admin/users/{user_id}", headers={"X-Admin-Key": "sk-admin-test"})
    create_user_with_credentials(client, "alice-again", account_id="acc-alice")
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("cookie", ["", "forged-cookie"])
def test_should_reject_missing_or_forged_session(client, cookie):
    client.cookies.set(COOKIE, cookie)
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/login"


def test_should_reject_expired_session(client, monkeypatch):
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        identity = {
            "id": user.id,
            "account": user.account_id,
            "created": user.created_at.isoformat(),
        }
    signer = session_signer()
    with monkeypatch.context() as signing_clock:
        signing_clock.setattr(signer.signer, "get_timestamp", lambda _: 1)
        client.cookies.set(COOKIE, signer.dumps(identity))
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


@respx.mock
def test_should_reject_state_mismatch_without_token_exchange(client):
    client.post("/dashboard/login/start")
    response = client.post(
        "/dashboard/login/complete",
        json={"callbackUrl": "http://localhost:1455/auth/callback?code=code&state=wrong"},
    )
    assert response.status_code == 400
    assert len(respx.calls) == 0


def test_should_keep_dashboard_and_registration_flows_separate(client):
    dashboard = client.get("/dashboard/login").text
    assert "/dashboard/login/start" in dashboard
    assert "não cria conta nem altera API keys" in dashboard
    registration = client.get("/login").text
    assert "fetch('/login/start'" in registration
    assert "Cada login gera uma nova key" in registration


def test_should_refuse_insecure_dashboard_secret(client, monkeypatch):
    monkeypatch.setattr(client.app.state.settings, "cookie_secret", "chatgpt-proxy-dev-secret")
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cookie_secret", "chatgpt-proxy-dev-secret")
    response = client.post("/dashboard/login/start")
    assert response.status_code == 503
    assert "COOKIE_SECRET" in response.text
