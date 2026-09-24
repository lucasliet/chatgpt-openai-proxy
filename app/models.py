"""Modelos SQLModel: usuários, API keys e settings (key-value).

`Setting` guarda as credenciais OAuth do ChatGPT quando elas vêm do fluxo
/login (alternativa às env vars). Uma linha por chave; a chave
`chatgpt_credentials` contém um JSON com access_token, refresh_token,
expires_at (ms epoch) e account_id.
"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "proxy_user"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow)


class ApiKey(SQLModel, table=True):
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


class Setting(SQLModel, table=True):
    __tablename__ = "proxy_setting"

    key: str = Field(primary_key=True)
    value: str = ""
