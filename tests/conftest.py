"""Fixtures compartilhadas dos testes.

Cada teste recebe um app fresco com banco SQLite em diretório temporário,
ADMIN_API_KEY fixa e engine httpx (upstream Codex mockado via respx). Não há
credenciais globais: usuários são criados com credenciais OAuth próprias
via ``create_user_with_credentials``.
"""

import time

import pytest
from fastapi.testclient import TestClient


def _setup_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("ADMIN_API_KEY", "sk-admin-test")
    # Engine httpx nos testes: interceptável deterministicamente pelo respx.
    monkeypatch.setenv("UPSTREAM_ENGINE", "httpx")


def _build_client(monkeypatch, tmp_path) -> TestClient:
    from app import database
    from app.config import get_settings
    from app.main import create_app

    _setup_env(monkeypatch, tmp_path)
    database.reset_engine()
    get_settings.cache_clear()

    app = create_app()
    client = TestClient(app)
    database.reset_engine()
    get_settings.cache_clear()
    return client


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    """TestClient com banco isolado e admin key fixa."""
    with _build_client(monkeypatch, tmp_path) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": "sk-admin-test"}


def create_user_with_credentials(
    client: TestClient,
    name: str,
    account_id: str = "acc-1",
    expires_in_s: int = 3600,
) -> int:
    """Cria usuário (via admin) e grava credenciais OAuth direto no banco."""
    from sqlmodel import Session

    from app.database import get_engine
    from app.models import User

    created = client.post("/admin/users", json={"name": name}, headers={"X-Admin-Key": "sk-admin-test"})
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        assert user is not None
        user.account_id = account_id
        user.access_token = f"at-{account_id}"
        user.refresh_token = f"rt-{account_id}"
        user.expires_at = int((time.time() + expires_in_s) * 1000)
        session.add(user)
        session.commit()

    return user_id


def create_api_key(client: TestClient, user_id: int, label: str = "teste") -> str:
    key = client.post(
        f"/admin/users/{user_id}/keys",
        json={"label": label},
        headers={"X-Admin-Key": "sk-admin-test"},
    )
    assert key.status_code == 201, key.text
    return key.json()["key"]


@pytest.fixture()
def user_key(client, admin_headers) -> str:
    """Usuário com credenciais + API key; retorna a chave completa."""
    user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
    return create_api_key(client, user_id)


@pytest.fixture()
def auth_headers(user_key) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_key}"}
