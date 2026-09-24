"""Fixtures compartilhadas dos testes.

Cada teste recebe um app fresco com banco SQLite em diretório temporário,
ADMIN_API_KEY fixa e credenciais ChatGPT via env (exceto nos testes de
login/credenciais, que usam `client_sem_env_creds`).
"""

import time

import pytest
from fastapi.testclient import TestClient


def _setup_env(monkeypatch, tmp_path, with_env_credentials: bool) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("ADMIN_API_KEY", "sk-admin-test")
    # Engine httpx nos testes: interceptável deterministicamente pelo respx.
    monkeypatch.setenv("UPSTREAM_ENGINE", "httpx")
    if with_env_credentials:
        expires = int((time.time() + 3600) * 1000)
        monkeypatch.setenv("CHATGPT_ACCESS_TOKEN", "access-token-env")
        monkeypatch.setenv("CHATGPT_REFRESH_TOKEN", "refresh-token-env")
        monkeypatch.setenv("CHATGPT_ACCOUNT_ID", "acc-env-123")
        monkeypatch.setenv("CHATGPT_EXPIRES_AT", str(expires))
    else:
        for var in (
            "CHATGPT_ACCESS_TOKEN",
            "CHATGPT_REFRESH_TOKEN",
            "CHATGPT_ACCOUNT_ID",
            "CHATGPT_EXPIRES_AT",
        ):
            monkeypatch.delenv(var, raising=False)


def _build_client(monkeypatch, tmp_path, with_env_credentials: bool) -> TestClient:
    from app import database
    from app.config import get_settings
    from app.main import create_app

    _setup_env(monkeypatch, tmp_path, with_env_credentials)
    database.reset_engine()
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)
    database.reset_engine()
    get_settings.cache_clear()
    return client


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    """TestClient com credenciais ChatGPT vindas de env (read-only)."""
    with _build_client(monkeypatch, tmp_path, True) as test_client:
        yield test_client


@pytest.fixture()
def client_sem_env_creds(monkeypatch, tmp_path) -> TestClient:
    """TestClient sem credenciais em env (fluxo de login no banco)."""
    with _build_client(monkeypatch, tmp_path, False) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": "sk-admin-test"}


@pytest.fixture()
def user_key(client, admin_headers) -> str:
    """Cria um usuário e uma API key e retorna a chave completa."""
    user = client.post("/admin/users", json={"name": "alice"}, headers=admin_headers)
    assert user.status_code == 201, user.text
    key = client.post(
        f"/admin/users/{user.json()['id']}/keys", json={"label": "teste"}, headers=admin_headers
    )
    assert key.status_code == 201, key.text
    return key.json()["key"]


@pytest.fixture()
def auth_headers(user_key) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_key}"}
