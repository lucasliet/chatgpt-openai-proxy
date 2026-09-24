"""Carregamento, refresh e persistência das credenciais ChatGPT.

Precedência: variáveis de ambiente (headless, read-only) > banco de dados
(linha `chatgpt_credentials` na tabela Setting, gravada pelo fluxo /login).

O refresh pró-ativo acontece quando o token expira em menos de 5 minutos. Um
lock de processo serializa o refresh; em deploys multi-instância (FastAPI
Cloud) a janela de corrida entre instâncias é aceitável porque o refresh só
ocorre uma vez a cada ~55 minutos e o refresh token da OpenAI tolera reúso
recente. Credenciais vindas de env nunca são persistidas.
"""

import asyncio
import json
import time
from typing import Literal

from sqlmodel import Session, select

from .config import Settings
from .models import Setting
from .oauth import Credentials, refresh_access_token

CREDENTIALS_SETTING_KEY = "chatgpt_credentials"
REFRESH_BUFFER_MS = 5 * 60 * 1000

_refresh_lock = asyncio.Lock()


def _env_credentials(settings: Settings) -> Credentials | None:
    """Credenciais vindas de env vars; só valem se todas existirem."""
    access = settings.chatgpt_access_token
    refresh = settings.chatgpt_refresh_token
    account_id = settings.chatgpt_account_id
    expires_raw = settings.chatgpt_expires_at
    if not access or not refresh or not account_id or not expires_raw:
        return None
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None
    return Credentials(
        access_token=access,
        refresh_token=refresh,
        account_id=account_id,
        expires_at=expires_at,
    )


def load_credentials(
    session: Session, settings: Settings
) -> tuple[Credentials, Literal["env", "db"]] | None:
    """Carrega as credenciais ativas (env tem precedência sobre o banco)."""
    from_env = _env_credentials(settings)
    if from_env:
        return from_env, "env"

    row = session.get(Setting, CREDENTIALS_SETTING_KEY)
    if row and row.value:
        try:
            return Credentials.from_json(row.value), "db"
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
    return None


def save_credentials(session: Session, credentials: Credentials) -> None:
    """Persiste as credenciais no banco (upset na tabela Setting)."""
    row = session.get(Setting, CREDENTIALS_SETTING_KEY)
    if row is None:
        row = Setting(key=CREDENTIALS_SETTING_KEY, value=credentials.to_json())
    else:
        row.value = credentials.to_json()
    session.add(row)
    session.commit()


def delete_credentials(session: Session) -> None:
    """Remove as credenciais do banco."""
    row = session.get(Setting, CREDENTIALS_SETTING_KEY)
    if row:
        session.delete(row)
        session.commit()


async def get_valid_credentials(session: Session, settings: Settings) -> Credentials | None:
    """Garante credenciais frescas, renovando quando perto da expiração."""
    loaded = load_credentials(session, settings)
    if loaded is None:
        return None
    credentials, source = loaded

    if credentials.expires_at > int(time.time() * 1000) + REFRESH_BUFFER_MS:
        return credentials
    if not credentials.refresh_token:
        return credentials

    async with _refresh_lock:
        # Re-leitura dentro do lock: outra requisição pode já ter renovado.
        loaded = load_credentials(session, settings)
        if loaded is None:
            return None
        credentials, source = loaded
        if credentials.expires_at > int(time.time() * 1000) + REFRESH_BUFFER_MS:
            return credentials

        try:
            token = await refresh_access_token(settings, credentials.refresh_token)
        except Exception:
            return credentials

        refreshed = Credentials(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token") or credentials.refresh_token,
            account_id=credentials.account_id,
            expires_at=int(time.time() * 1000) + int(token.get("expires_in", 0)) * 1000,
        )
        if source == "db":
            save_credentials(session, refreshed)
        return refreshed
