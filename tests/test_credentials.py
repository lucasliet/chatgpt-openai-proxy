"""Testes do store de credenciais: precedência env > banco e refresh."""

import time

import pytest
import respx
from httpx import Response
from sqlmodel import Session

from app.config import get_settings
from app.credentials import (
    delete_credentials,
    get_valid_credentials,
    load_credentials,
    save_credentials,
)
from app.database import get_engine
from app.oauth import Credentials


def _db_session() -> Session:
    return Session(get_engine())


def _credentials(expires_at: int) -> Credentials:
    return Credentials(
        access_token="at-db",
        refresh_token="rt-db",
        account_id="acc-db",
        expires_at=expires_at,
    )


class TestPrecedencia:
    def test_env_tem_precedencia_sobre_db(self, client):
        with _db_session() as session:
            save_credentials(session, _credentials(int((time.time() + 3600) * 1000)))
            loaded = load_credentials(session, get_settings())
        assert loaded is not None
        credentials, source = loaded
        assert source == "env"
        assert credentials.access_token == "access-token-env"

    def test_db_quando_sem_env(self, client_sem_env_creds):
        with _db_session() as session:
            save_credentials(session, _credentials(int((time.time() + 3600) * 1000)))
            loaded = load_credentials(session, get_settings())
        assert loaded is not None
        credentials, source = loaded
        assert source == "db"
        assert credentials.access_token == "at-db"

    def test_expires_at_nao_numerico_env_ignorado(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/x.db")
        monkeypatch.setenv("CHATGPT_ACCESS_TOKEN", "at")
        monkeypatch.setenv("CHATGPT_REFRESH_TOKEN", "rt")
        monkeypatch.setenv("CHATGPT_ACCOUNT_ID", "acc")
        monkeypatch.setenv("CHATGPT_EXPIRES_AT", "nao-numero")
        from app.config import get_settings as gs

        gs.cache_clear()
        from app.credentials import _env_credentials

        assert _env_credentials(gs()) is None

    def test_delete_credentials(self, client_sem_env_creds):
        with _db_session() as session:
            save_credentials(session, _credentials(int((time.time() + 3600) * 1000)))
            delete_credentials(session)
            assert load_credentials(session, get_settings()) is None


class TestRefresh:
    @respx.mock
    async def test_refresh_quando_perto_da_expiracao(self, client_sem_env_creds):
        settings = get_settings()
        expirando = int((time.time() + 60) * 1000)  # expira em 1 min
        with _db_session() as session:
            save_credentials(session, _credentials(expirando))

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
            credentials = await get_valid_credentials(session, settings)

        assert credentials.access_token == "at-novo"
        assert credentials.refresh_token == "rt-novo"
        assert credentials.account_id == "acc-db"  # account id é preservado

        # Persistido no banco.
        with _db_session() as session:
            loaded = load_credentials(session, settings)
        assert loaded is not None
        assert loaded[0].access_token == "at-novo"

    @respx.mock
    async def test_refresh_env_nao_persiste(self, client):
        settings = get_settings()
        original_expires = settings.chatgpt_expires_at
        original_access = settings.chatgpt_access_token
        settings.chatgpt_expires_at = str(int((time.time() + 60) * 1000))
        try:
            respx.post(settings.oauth_token_url).mock(
                return_value=Response(200, json={"access_token": "at-env-novo", "expires_in": 3600})
            )
            with _db_session() as session:
                credentials = await get_valid_credentials(session, settings)
            assert credentials.access_token == "at-env-novo"
            # Nada gravado no banco: a origem continua "env".
            with _db_session() as session:
                loaded = load_credentials(session, settings)
            assert loaded is not None
            assert loaded[1] == "env"
        finally:
            settings.chatgpt_expires_at = original_expires
            settings.chatgpt_access_token = original_access

    @respx.mock
    async def test_refresh_falha_mantem_credencial_antiga(self, client_sem_env_creds):
        settings = get_settings()
        expirando = int((time.time() + 60) * 1000)
        with _db_session() as session:
            save_credentials(session, _credentials(expirando))

        respx.post(settings.oauth_token_url).mock(return_value=Response(400, text="invalid_grant"))

        with _db_session() as session:
            credentials = await get_valid_credentials(session, settings)
        assert credentials.access_token == "at-db"

    async def test_token_longo_nao_refresca(self, client_sem_env_creds):
        settings = get_settings()
        with _db_session() as session:
            save_credentials(session, _credentials(int((time.time() + 3600) * 1000)))
            credentials = await get_valid_credentials(session, settings)
        assert credentials.access_token == "at-db"

    async def test_sem_credenciais_retorna_none(self, client_sem_env_creds):
        with _db_session() as session:
            assert await get_valid_credentials(session, get_settings()) is None
