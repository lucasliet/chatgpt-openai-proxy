"""Fluxo OAuth PKCE do ChatGPT Plan (Codex) — port do proxy original.

Inclui geração de verifier/state, construção da URL de autorização, troca do
authorization code por tokens e refresh do access token. O `account_id` é
extraído do `id_token` (JWT decodificado sem verificação, como no proxy
original — o token chega por TLS direto do endpoint de token da OpenAI).
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings, oauth_redirect_uri

_PKCE_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


@dataclass
class Credentials:
    """Credenciais OAuth do ChatGPT em uso pelo proxy."""

    access_token: str
    refresh_token: str
    account_id: str
    expires_at: int  # ms epoch

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "account_id": self.account_id,
                "expires_at": self.expires_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "Credentials":
        data = json.loads(raw)
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            account_id=data.get("account_id", ""),
            expires_at=int(data["expires_at"]),
        )


def _random_string(length: int) -> str:
    return "".join(secrets.choice(_PKCE_CHARSET) for _ in range(length))


def generate_code_verifier() -> str:
    """Verifier PKCE de 64 caracteres do conjunto não reservado (RFC 7636)."""
    return _random_string(64)


def generate_state() -> str:
    """State aleatório de 32 caracteres contra CSRF."""
    return _random_string(32)


def code_challenge(verifier: str) -> str:
    """Challenge S256: base64url(SHA-256(verifier)) sem padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_auth_url(settings: Settings, verifier: str, state: str) -> str:
    """URL de autorização PKCE com os parâmetros específicos do fluxo Codex."""
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": settings.oauth_client_id,
        "redirect_uri": oauth_redirect_uri(settings),
        "scope": settings.oauth_scope,
        "state": state,
        "code_challenge": code_challenge(verifier),
        "code_challenge_method": "S256",
        "codex_cli_simplified_flow": "true",
        "originator": "codex_cli_rs",
    }
    return f"{settings.oauth_auth_url}?{urlencode(params)}"


async def exchange_code_for_tokens(
    settings: Settings, code: str, verifier: str
) -> dict[str, Any]:
    """Troca o authorization code por tokens (PKCE)."""
    body = {
        "grant_type": "authorization_code",
        "client_id": settings.oauth_client_id,
        "code": code,
        "redirect_uri": oauth_redirect_uri(settings),
        "code_verifier": verifier,
    }
    return await _post_token_request(settings, body)


async def refresh_access_token(settings: Settings, refresh_token: str) -> dict[str, Any]:
    """Renova o access token com o refresh token de longa duração."""
    body = {
        "grant_type": "refresh_token",
        "client_id": settings.oauth_client_id,
        "refresh_token": refresh_token,
    }
    return await _post_token_request(settings, body)


async def _post_token_request(settings: Settings, body: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.oauth_token_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Token request failed ({response.status_code}): {response.text}"
        )
    return response.json()


def token_to_credentials(token: dict[str, Any], fallback_account_id: str = "") -> Credentials:
    """Converte a resposta de token em Credentials, extraindo o account id."""
    account_id = ""
    if token.get("id_token"):
        account_id = extract_account_id(token["id_token"]) or ""
    return Credentials(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token", ""),
        account_id=account_id or fallback_account_id,
        expires_at=_now_ms() + int(token.get("expires_in", 0)) * 1000,
    )


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _decode_base64url(value: str) -> bytes:
    normalized = value.replace("-", "+").replace("_", "/")
    normalized += "=" * (-len(normalized) % 4)
    return base64.b64decode(normalized)


def parse_jwt_claims(token: str) -> dict[str, Any] | None:
    """Decodifica o payload de um JWT sem verificar assinatura."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        return json.loads(_decode_base64url(parts[1]))
    except Exception:
        return None


def extract_account_id(id_token: str) -> str | None:
    """Extrai o ChatGPT account id das claims conhecidas do id_token."""
    claims = parse_jwt_claims(id_token)
    if not claims:
        return None
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    return (
        claims.get("chatgpt_account_id")
        or auth_claims.get("chatgpt_account_id")
        or (claims.get("organizations") or [{}])[0].get("id")
    )
