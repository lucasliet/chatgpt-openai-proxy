"""Geração e verificação de API keys da aplicação e auth de admin.

As chaves seguem o formato `sk-<urlsafe>`. Apenas o hash SHA-256 (com salt
fixo da aplicação) é persistido — a chave completa é retornada uma única vez
no momento da criação.
"""

import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

KEY_PREFIX = "sk-"
_KEY_SALT = "chatgpt-openai-proxy:v1"


def generate_api_key() -> str:
    """Gera uma nova API key no formato `sk-<43 chars urlsafe>`."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """Hash irreversível da chave para armazenamento e lookup."""
    return hashlib.sha256((_KEY_SALT + key).encode()).hexdigest()


def key_prefix(key: str) -> str:
    """Prefixo exibível da chave (12 primeiros caracteres)."""
    return key[:12]


def require_admin(
    settings: Settings = Depends(get_settings),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Dependency que exige o header X-Admin-Key correto nos endpoints /admin."""
    expected = settings.admin_api_key
    if not expected or not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "message": "Admin key inválida ou ausente. Envie o header X-Admin-Key.",
                    "type": "authentication_error",
                    "code": "invalid_admin_key",
                }
            },
        )
