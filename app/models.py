"""Modelos SQLModel: usuários (com credenciais OAuth) e API keys.

Cada usuário autentica a **própria conta ChatGPT** via OAuth (fluxo /login);
os tokens ficam na linha do usuário e o refresh automático acontece por
usuário, com lock por conta. A API key (`sk-...`) é o que o cliente usa para
falar com o proxy — ela aponta para o usuário, e o proxy usa a assinatura
OAuth daquele usuário upstream.

Os tokens são cifrados em repouso (Fernet) pela coluna ``EncryptedText`` de
``app/crypto.py`` — no banco só existe ciphertext; a chave vem de
``TOKEN_ENCRYPTION_KEY`` ou do keyfile ``token.key`` no proxy home.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column
from sqlmodel import Field, SQLModel

from .crypto import EncryptedText


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """Usuário do proxy, com a credencial OAuth do ChatGPT dele."""

    __tablename__ = "proxy_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    # Identidade estável da conta ChatGPT (do id_token); usada para fazer
    # upsert no re-login sem duplicar usuário. NULL = conta ainda não
    # autenticada (NULLs não conflitam na unique constraint).
    account_id: str | None = Field(default=None, unique=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None

    # Credencial OAuth da assinatura ChatGPT deste usuário (cifrada em repouso).
    access_token: str = Field(
        default="", sa_column=Column(EncryptedText, nullable=False, server_default="")
    )
    refresh_token: str = Field(
        default="", sa_column=Column(EncryptedText, nullable=False, server_default="")
    )
    expires_at: int = Field(default=0, sa_type=BigInteger)  # ms epoch; 0 = não autenticado


class ApiKey(SQLModel, table=True):
    """API key da aplicação, atrelada a um usuário."""

    __tablename__ = "proxy_api_key"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="proxy_user.id", index=True)
    label: str = ""
    # Primeiros caracteres da chave, só para exibição (a chave completa nunca
    # é armazenada).
    prefix: str
    key_hash: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
