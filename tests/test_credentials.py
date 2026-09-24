"""Testes do store de credenciais por usuário e do refresh."""

import time

import respx
from httpx import Response
from sqlmodel import Session

from app.config import get_settings
from app.credentials import (
    credentials_from_user,
    get_valid_user_credentials,
    save_oauth_credentials,
)
from app.database import get_engine
from app.models import User
from app.oauth import Credentials

from conftest import create_api_key, create_user_with_credentials


def _db_session() -> Session:
    return Session(get_engine())


def _make_credentials(account_id: str = "acc-x", expires_at: int | None = None) -> Credentials:
    return Credentials(
        access_token=f"at-{account_id}",
        refresh_token=f"rt-{account_id}",
        account_id=account_id,
        expires_at=expires_at or int((time.time() + 3600) * 1000),
    )


def _get_user(user_id: int) -> User:
    with _db_session() as session:
        return session.get(User, user_id)


class TestCredentialsFromUser:
    def test_sem_access_token_retorna_none(self, client):
        created = client.post("/admin/users", json={"name": "vazio"}, headers={"X-Admin-Key": "sk-admin-test"})
        user = _get_user(created.json()["id"])
        assert credentials_from_user(user) is None

    def test_com_access_token_monta_credentials(self, client):
        user_id = create_user_with_credentials(client, "fulano", account_id="acc-fulano")
        credentials = credentials_from_user(_get_user(user_id))
        assert credentials is not None
        assert credentials.access_token == "at-acc-fulano"
        assert credentials.account_id == "acc-fulano"


class TestSaveOauthCredentials:
    def test_persiste_tokens_e_last_login(self, client):
        created = client.post("/admin/users", json={"name": "novo"}, headers={"X-Admin-Key": "sk-admin-test"})
        user_id = created.json()["id"]
        with _db_session() as session:
            user = session.get(User, user_id)
            save_oauth_credentials(session, user, _make_credentials("acc-novo"))
        user = _get_user(user_id)
        assert user.access_token == "at-acc-novo"
        assert user.account_id == "acc-novo"
        assert user.last_login_at is not None


class TestRefresh:
    async def test_token_longo_nao_refresca(self, client):
        user_id = create_user_with_credentials(client, "valido", account_id="acc-valido")
        with _db_session() as session:
            credentials = await get_valid_user_credentials(
                session, session.get(User, user_id), get_settings()
            )
        assert credentials is not None
        assert credentials.access_token == "at-acc-valido"

    @respx.mock
    async def test_refresh_quando_perto_da_expiracao(self, client):
        settings = get_settings()
        user_id = create_user_with_credentials(
            client, "expirando", account_id="acc-exp", expires_in_s=60
        )
        respx.post(settings.oauth_token_url).mock(
            return_value=Response(
                200,
                json={
                    "access_token": "at-novo",
                    "refresh_token": "rt-novo",
                    "expires_in": 3600,
                },
            )
        )

        with _db_session() as session:
            user = session.get(User, user_id)
            credentials = await get_valid_user_credentials(session, user, settings)

        assert credentials is not None
        assert credentials.access_token == "at-novo"
        assert credentials.refresh_token == "rt-novo"
        assert credentials.account_id == "acc-exp"  # account id preservado

        # Persistido na linha do usuário.
        user = _get_user(user_id)
        assert user.access_token == "at-novo"
        assert user.refresh_token == "rt-novo"

    @respx.mock
    async def test_refresh_falha_mantem_token_antigo(self, client):
        settings = get_settings()
        user_id = create_user_with_credentials(
            client, "falha", account_id="acc-falha", expires_in_s=60
        )
        respx.post(settings.oauth_token_url).mock(return_value=Response(400, text="invalid_grant"))

        with _db_session() as session:
            user = session.get(User, user_id)
            credentials = await get_valid_user_credentials(session, user, settings)

        assert credentials is not None
        assert credentials.access_token == "at-acc-falha"


class TestRefreshIsoladoPorUsuario:
    @respx.mock
    async def test_refresh_de_um_nao_afeta_outro(self, client):
        settings = get_settings()
        user_a = create_user_with_credentials(client, "user-a", account_id="acc-a", expires_in_s=60)
        user_b = create_user_with_credentials(client, "user-b", account_id="acc-b", expires_in_s=60)

        respx.post(settings.oauth_token_url).mock(
            return_value=Response(200, json={"access_token": "at-novo-a", "expires_in": 3600})
        )

        with _db_session() as session:
            await get_valid_user_credentials(session, session.get(User, user_a), settings)

        assert _get_user(user_a).access_token == "at-novo-a"
        assert _get_user(user_b).access_token == "at-acc-b"


class TestApiKeySemCredencial:
    def test_key_de_usuario_sem_oauth_recebe_401(self, client):
        created = client.post("/admin/users", json={"name": "sem-oauth"}, headers={"X-Admin-Key": "sk-admin-test"})
        key = create_api_key(client, created.json()["id"])

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-5.1-codex", "messages": [{"role": "user", "content": "oi"}]},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "no_credentials"

    def test_listagem_admin_mostra_status_da_credencial(self, client):
        create_user_with_credentials(client, "com-oauth", account_id="acc-conta-123")
        client.post("/admin/users", json={"name": "sem-oauth"}, headers={"X-Admin-Key": "sk-admin-test"})

        users = client.get("/admin/users", headers={"X-Admin-Key": "sk-admin-test"}).json()["users"]
        by_name = {u["name"]: u for u in users}
        assert by_name["com-oauth"]["credential"]["authenticated"] is True
        assert by_name["com-oauth"]["credential"]["account_id"] == "acc-...-123"
        assert by_name["sem-oauth"]["credential"]["authenticated"] is False
