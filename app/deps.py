"""Dependências FastAPI: autenticação por API key e credenciais upstream.

Toda rota de proxy exige ``Authorization: Bearer sk-...``. A chave é
resolvida por hash (SHA-256 com salt da aplicação) e atrelada a um usuário;
chaves revogadas ou inexistentes recebem 401 no formato de erro da OpenAI.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlmodel import Session, select

from .config import Settings, get_settings
from .credentials import get_valid_credentials
from .database import get_session
from .models import ApiKey, User, utcnow
from .oauth import Credentials
from .security import hash_api_key


@dataclass
class AuthContext:
    """Usuário autenticado e a API key usada na requisição."""

    user: User
    api_key: ApiKey


def _unauthorized(message: str, code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "message": message,
                "type": "authentication_error",
                "code": code,
            }
        },
    )


def require_api_key(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[Session, Depends(get_session)] = None,
) -> AuthContext:
    """Dependency que autentica a requisição via Bearer API key."""
    assert session is not None
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized(
            "API key ausente. Envie Authorization: Bearer <sua-chave>.",
            "missing_api_key",
        )

    key = authorization[len("Bearer ") :].strip()
    api_key = session.exec(
        select(ApiKey).where(
            ApiKey.key_hash == hash_api_key(key),
            ApiKey.revoked_at.is_(None),  # type: ignore[attr-defined]
        )
    ).first()
    if api_key is None:
        raise _unauthorized("API key inválida ou revogada.", "invalid_api_key")

    user = session.get(User, api_key.user_id)
    if user is None:
        raise _unauthorized("Usuário da API key não existe.", "invalid_api_key")

    api_key.last_used_at = utcnow()
    session.add(api_key)
    session.commit()

    return AuthContext(user=user, api_key=api_key)


async def require_credentials(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Credentials:
    """Garante credenciais ChatGPT válidas (refresh pró-ativo) ou 401."""
    settings: Settings = get_settings()
    credentials = await get_valid_credentials(session, settings)
    if credentials is None:
        raise _unauthorized(
            "Nenhuma credencial ChatGPT configurada. Acesse /login ou defina as env vars CHATGPT_*.",
            "no_credentials",
        )
    return credentials
