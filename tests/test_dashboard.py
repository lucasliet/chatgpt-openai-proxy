import re

import pytest
import respx
from conftest import create_api_key, create_user_with_credentials
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import get_engine
from app.models import ApiKey, User, utcnow
from app.routers.dashboard import COOKIE, session_signer
from app.telemetry import record_usage


def authenticate(client, key):
    page = client.get("/dashboard/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    return client.post(
        "/dashboard/login", data={"key": key, "csrf_token": token}, follow_redirects=False
    )


@respx.mock
def test_should_authenticate_existing_user_without_changing_credentials_or_keys(client):
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    key = create_api_key(client, user_id)
    with Session(get_engine()) as session:
        original = session.get(User, user_id).model_dump()
    response = authenticate(client, key)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    assert key not in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert len(respx.calls) == 0
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert client.get("/dashboard").status_code == 200
    with Session(get_engine()) as session:
        assert session.get(User, user_id).model_dump() == original
        keys = session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all()
        assert len(keys) == 1
        assert keys[0].revoked_at is None
    assert key.startswith("sk-")


@pytest.mark.parametrize("key", ["", "unknown-key", "sk-admin-test"])
def test_should_not_register_unknown_account(client, key):
    response = authenticate(client, key)
    assert response.status_code == 401
    assert "API key inválida ou revogada" in response.text
    assert response.headers["cache-control"] == "no-store"
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
    authenticate(client, create_api_key(client, alice))
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
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    authenticate(client, create_api_key(client, user_id))
    response = client.get(f"/dashboard?days={days}")
    assert response.status_code == 200
    assert f'href="/dashboard?days={days}" aria-current=page' in response.text


@respx.mock
def test_should_logout_session_without_deleting_account(client):
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    authenticate(client, create_api_key(client, user_id))
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
    authenticate(client, create_api_key(client, user_id))
    client.delete(f"/admin/users/{user_id}", headers={"X-Admin-Key": "sk-admin-test"})
    new_id = create_user_with_credentials(client, "alice-again", account_id="acc-alice")
    create_api_key(client, new_id)
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("cookie", ["", "forged-cookie"])
def test_should_reject_missing_or_forged_session(client, cookie):
    client.cookies.set(COOKIE, cookie)
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/login"


def test_should_reject_expired_session(client, user_key, monkeypatch):
    authenticate(client, user_key)
    signer = session_signer()
    identity = signer.loads(client.cookies.get(COOKIE))
    with monkeypatch.context() as signing_clock:
        signing_clock.setattr(signer.signer, "get_timestamp", lambda _: 1)
        client.cookies.set(COOKIE, signer.dumps(identity))
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_should_reject_revoked_key_and_invalidate_its_session(client, user_key):
    authenticate(client, user_key)
    with Session(get_engine()) as session:
        key = session.exec(select(ApiKey)).first()
        key.revoked_at = utcnow()
        session.add(key)
        session.commit()
    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    response = authenticate(client, user_key)
    assert response.status_code == 401
    assert user_key not in response.text


def test_should_keep_dashboard_and_registration_flows_separate(client):
    dashboard = client.get("/dashboard/login").text
    assert 'action="/dashboard/login"' in dashboard
    assert 'type="password"' in dashboard
    assert "Sua API key" in dashboard
    assert "/dashboard/login/start" not in dashboard
    assert client.post("/dashboard/login/start").status_code == 404
    assert client.post("/dashboard/login/complete").status_code == 404
    registration = client.get("/login").text
    assert "fetch('/login/start'" in registration
    assert "Cada login gera uma nova key" in registration


def test_should_refuse_insecure_dashboard_secret(client, monkeypatch):
    monkeypatch.setattr(client.app.state.settings, "cookie_secret", "chatgpt-proxy-dev-secret")
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "cookie_secret", "chatgpt-proxy-dev-secret")
    response = authenticate(client, "any-key")
    assert response.status_code == 503
    assert "COOKIE_SECRET" in response.text


def test_should_document_key_access_without_administrator_flow(client):
    page = client.get("/").text
    assert "informando sua API key do proxy" in page
    assert "self-service" not in page
    assert "O administrador do serviço consulta" not in page
    assert "após login com sua conta ChatGPT já cadastrada" not in page


@respx.mock
def test_should_allow_usage_access_without_valid_upstream_credentials(client, user_key):
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
        user.access_token = ""
        user.refresh_token = ""
        user.expires_at = 0
        session.add(user)
        session.commit()
    assert authenticate(client, user_key).status_code == 303
    assert client.get("/dashboard").status_code == 200
    assert len(respx.calls) == 0


@pytest.mark.parametrize("csrf_token", [None, "wrong-token", "inválido"])
def test_should_reject_external_login_without_replacing_session(client, user_key, csrf_token):
    authenticate(client, user_key)
    original_cookie = client.cookies.get(COOKIE)
    bob = create_user_with_credentials(client, "bob", account_id="acc-bob")
    bob_key = create_api_key(client, bob)
    client.get("/dashboard/login")
    form = {"key": bob_key}
    if csrf_token is not None:
        form["csrf_token"] = csrf_token
    response = client.post(
        "/dashboard/login",
        data=form,
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert client.cookies.get(COOKIE) == original_cookie
    assert "Consumo de alice" in client.get("/dashboard").text
    with Session(get_engine()) as session:
        key = session.exec(select(ApiKey).where(ApiKey.user_id == bob)).first()
        assert key.last_used_at is None


def test_should_require_csrf_token_bound_to_browser_session(client, user_key):
    page = client.get("/dashboard/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    client.cookies.clear()
    response = client.post(
        "/dashboard/login",
        data={"key": user_key, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert COOKIE not in client.cookies


@pytest.mark.parametrize("mount_name", [None, "proxy"])
def test_should_keep_login_and_session_navigation_inside_mounted_app(client, user_key, mount_name):
    outer = FastAPI()
    outer.mount("/proxy", client.app, name=mount_name)
    leaked_keys = []

    @outer.post("/dashboard/login")
    async def unrelated_service(request: Request):
        leaked_keys.append((await request.form()).get("key"))
        return {"received": True}

    with TestClient(outer) as mounted:
        protected = mounted.get("/proxy/dashboard", follow_redirects=False)
        assert protected.headers["location"] == "/proxy/dashboard/login"
        page = mounted.get(protected.headers["location"])
        action = re.search(r'<form method="post" action="([^"]+)"', page.text).group(1)
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        assert action == "/proxy/dashboard/login"
        assert 'href="/proxy/"' in page.text
        invalid = mounted.post(
            action, data={"key": "wrong", "csrf_token": token}, follow_redirects=False
        )
        assert invalid.status_code == 401
        assert f'action="{action}"' in invalid.text
        response = mounted.post(
            action, data={"key": user_key, "csrf_token": token}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/proxy/dashboard"
        usage = mounted.get(response.headers["location"])
        assert usage.status_code == 200
        assert 'href="/proxy/dashboard?days=7"' in usage.text
        assert 'action="/proxy/dashboard/logout"' in usage.text
        response = mounted.post("/proxy/dashboard/logout", follow_redirects=False)
        assert response.headers["location"] == "/proxy/dashboard/login"
        assert mounted.get("/proxy/dashboard", follow_redirects=False).status_code == 303
    assert leaked_keys == []
