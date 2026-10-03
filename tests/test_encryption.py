"""Testes da cifragem em repouso dos tokens OAuth (app/crypto.py).

Garante que nenhum token fica em texto puro no banco, que a leitura via ORM
continua transparente, que o boot migra tokens legados e rotaciona chaves
antigas, e que a chave errada falha com mensagem acionável.
"""

import base64

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app import crypto
from app.config import get_settings
from app.database import get_engine, init_db
from app.models import User
from conftest import create_user_with_credentials

# Segunda chave Fernet válida, diferente da usada no conftest.
OTHER_KEY = base64.urlsafe_b64encode(b"\x02" * 32).decode()


def _raw_tokens(user_id: int) -> tuple[str, str]:
    """Lê access/refresh token direto do banco, sem o TypeDecorator do ORM."""
    with get_engine().begin() as connection:
        row = connection.execute(
            text("SELECT access_token, refresh_token FROM proxy_user WHERE id = :id"),
            {"id": user_id},
        ).one()
    return row.access_token, row.refresh_token


def _reload_settings(key: str) -> None:
    import os

    os.environ["TOKEN_ENCRYPTION_KEY"] = key
    get_settings.cache_clear()
    crypto.reset_keyring()


class TestTokenEncryption:
    def test_tokens_ficam_cifrados_no_banco(self, client):
        # Given: usuário com credenciais OAuth gravadas pelo fluxo normal
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")

        # When: ler a linha crua no banco
        access_token, refresh_token = _raw_tokens(user_id)

        # Then: só ciphertext Fernet é persistido — nada de texto puro
        assert access_token.startswith(crypto.FERNET_PREFIX)
        assert refresh_token.startswith(crypto.FERNET_PREFIX)
        assert "at-acc-alice" not in access_token
        assert "rt-acc-alice" not in refresh_token

    def test_orm_decifra_transparentemente(self, client):
        # Given
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")

        # When: ler o usuário pelo ORM (passa pelo EncryptedText)
        with Session(get_engine()) as session:
            user = session.get(User, user_id)

        # Then: os valores originais voltam decifrados
        assert user is not None
        assert user.access_token == "at-acc-alice"
        assert user.refresh_token == "rt-acc-alice"

    def test_init_db_cifra_tokens_legados_em_texto_plano(self, client):
        # Given: linha legada com tokens em texto puro (escrita pré-cifragem,
        # via SQL cru para não passar pelo TypeDecorator)
        with get_engine().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO proxy_user (name, account_id, created_at, access_token, refresh_token, expires_at)"
                    " VALUES (:name, :account_id, :created_at, :access_token, :refresh_token, :expires_at)"
                ),
                {
                    "name": "legacy",
                    "account_id": "acc-legacy",
                    "created_at": "2026-01-01 00:00:00",
                    "access_token": "at-legado",
                    "refresh_token": "rt-legado",
                    "expires_at": 0,
                },
            )

        # When: rodar o boot (migração idempotente)
        init_db()

        # Then: o banco passa a ter ciphertext e o ORM devolve o valor original
        access_token, _ = _raw_tokens(1)
        assert access_token.startswith(crypto.FERNET_PREFIX)
        assert access_token != "at-legado"
        with Session(get_engine()) as session:
            legacy = session.exec(select(User).where(User.name == "legacy")).one()
        assert legacy.access_token == "at-legado"
        # E rodar de novo não muda nada (idempotente)
        init_db()
        assert _raw_tokens(legacy.id)[0] == access_token

    def test_init_db_rotaciona_tokens_de_chave_antiga(self, client):
        # Given: usuário cifrado com a chave do conftest
        user_id = create_user_with_credentials(client, "alice", account_id="acc-alice")
        old_ciphertext, _ = _raw_tokens(user_id)

        # When: a primária vira uma chave nova, mantendo a antiga no keyring
        _reload_settings(f"{OTHER_KEY},AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=")
        init_db()

        # Then: o ciphertext foi re-escrito com a nova primária e continua legível
        new_ciphertext, _ = _raw_tokens(user_id)
        assert new_ciphertext != old_ciphertext
        assert new_ciphertext.startswith(crypto.FERNET_PREFIX)
        with Session(get_engine()) as session:
            user = session.get(User, user_id)
        assert user.access_token == "at-acc-alice"

    def test_leitura_com_chave_errada_falha_com_mensagem_clara(self, client):
        # Given
        create_user_with_credentials(client, "alice", account_id="acc-alice")

        # When: a env passa a apontar para uma chave que não decifra os dados
        _reload_settings(OTHER_KEY)

        # Then: a leitura falha com erro acionável (nunca devolve lixo)
        with Session(get_engine()) as session, pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
            session.exec(select(User)).all()
