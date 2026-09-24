"""Refresh e persistência das credenciais OAuth **por usuário**.

Cada `User` carrega os tokens da própria conta ChatGPT. O refresh pró-ativo
acontece quando o token expira em menos de 5 minutos, serializado por usuário
(asyncio.Lock por conta). O refresh token da OpenAI pode rotacionar; a
substituição persiste na linha do usuário.

Em deploys multi-instância (FastAPI Cloud) a janela de corrida entre
instâncias é aceitável: o refresh só ocorre uma vez a cada ~55 minutos por
usuário e o backend tolera reúso recente do refresh token.
"""

import asyncio
import time

from sqlmodel import Session

from .config import Settings
from .models import User, utcnow
from .oauth import Credentials, refresh_access_token

REFRESH_BUFFER_MS = 5 * 60 * 1000

_locks: dict[int, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(user_id: int) -> asyncio.Lock:
    async with _locks_guard:
        lock = _locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _locks[user_id] = lock
        return lock


def credentials_from_user(user: User) -> Credentials | None:
    """Monta Credentials a partir da linha do usuário (None se não autenticado)."""
    if not user.access_token:
        return None
    return Credentials(
        access_token=user.access_token,
        refresh_token=user.refresh_token,
        account_id=user.account_id or "",
        expires_at=user.expires_at,
    )


def persist_credentials(session: Session, user: User, credentials: Credentials) -> None:
    """Grava os tokens na linha do usuário."""
    user.access_token = credentials.access_token
    user.refresh_token = credentials.refresh_token
    user.expires_at = credentials.expires_at
    if credentials.account_id and not user.account_id:
        user.account_id = credentials.account_id
    session.add(user)
    session.commit()


def save_oauth_credentials(
    session: Session, user: User, credentials: Credentials
) -> None:
    """Persiste o resultado de um login OAuth para o usuário."""
    persist_credentials(session, user, credentials)
    user.last_login_at = utcnow()
    session.add(user)
    session.commit()


async def get_valid_user_credentials(
    session: Session, user: User, settings: Settings
) -> Credentials | None:
    """Garante credenciais frescas do usuário, renovando quando necessário."""
    credentials = credentials_from_user(user)
    if credentials is None:
        return None

    now = int(time.time() * 1000)
    if credentials.expires_at > now + REFRESH_BUFFER_MS or not credentials.refresh_token:
        return credentials

    async with await _lock_for(user.id or 0):
        # Re-leitura dentro do lock: outra requisição pode já ter renovado.
        session.refresh(user)
        credentials = credentials_from_user(user)
        if credentials is None:
            return None
        if credentials.expires_at > int(time.time() * 1000) + REFRESH_BUFFER_MS:
            return credentials

        try:
            token = await refresh_access_token(settings, credentials.refresh_token)
        except Exception:
            return credentials  # mantém o token antigo; próxima tentativa renova

        refreshed = Credentials(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token") or credentials.refresh_token,
            account_id=credentials.account_id,
            expires_at=int(time.time() * 1000) + int(token.get("expires_in", 0)) * 1000,
        )
        persist_credentials(session, user, refreshed)
        return refreshed
