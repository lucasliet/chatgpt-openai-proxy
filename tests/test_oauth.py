"""Testes do módulo OAuth (PKCE, URL de autorização, JWT, troca/refresh)."""

import base64
import hashlib
import json

import pytest
import respx
from httpx import Response

from app.config import get_settings
from app.oauth import (
    build_auth_url,
    code_challenge,
    extract_account_id,
    generate_code_verifier,
    generate_state,
    parse_jwt_claims,
    refresh_access_token,
    exchange_code_for_tokens,
    token_to_credentials,
)


def _jwt(payload: dict) -> str:
    def encode(obj: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
        )

    return f"{encode({'alg': 'none'})}.{encode(payload)}."


class TestPkce:
    def test_verifier_charset_e_tamanho(self):
        verifier = generate_code_verifier()
        assert len(verifier) == 64
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" for c in verifier)

    def test_state_tem_32_chars(self):
        assert len(generate_state()) == 32

    def test_challenge_s256_sem_padding(self):
        challenge = code_challenge("abc")
        expected = base64.urlsafe_b64encode(hashlib.sha256(b"abc").digest()).rstrip(b"=").decode()
        assert challenge == expected
        assert "=" not in challenge


class TestJwt:
    def test_extract_account_id_claim_principal(self):
        token = _jwt({"chatgpt_account_id": "acc-1", "organizations": [{"id": "org-1"}]})
        assert extract_account_id(token) == "acc-1"

    def test_extract_account_id_claim_namespaced(self):
        token = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acc-2"}})
        assert extract_account_id(token) == "acc-2"

    def test_extract_account_id_fallback_organizations(self):
        token = _jwt({"organizations": [{"id": "org-9"}]})
        assert extract_account_id(token) == "org-9"

    def test_jwt_malformado_retorna_none(self):
        assert parse_jwt_claims("nao-eh-jwt") is None
        assert extract_account_id("xxx") is None


class TestAuthUrl:
    def test_parametros_codex(self):
        settings = get_settings()
        url = build_auth_url(settings, "verifier-x", "state-y")
        assert settings.oauth_auth_url in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "codex_cli_simplified_flow=true" in url
        assert "originator=codex_cli_rs" in url
        assert "state=state-y" in url
        assert f"redirect_uri=http%3A%2F%2Flocalhost%3A{settings.oauth_callback_port}%2Fauth%2Fcallback" in url


class TestTokenRequests:
    @respx.mock
    async def test_exchange_code_envia_pkce(self):
        settings = get_settings()
        route = respx.post(settings.oauth_token_url).mock(
            return_value=Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
        )
        token = await exchange_code_for_tokens(settings, "code-1", "verifier-1")
        assert token["access_token"] == "at"
        body = route.calls.last.request.content.decode()
        assert "grant_type=authorization_code" in body
        assert "code=code-1" in body
        assert "code_verifier=verifier-1" in body

    @respx.mock
    async def test_refresh_envia_refresh_token(self):
        settings = get_settings()
        route = respx.post(settings.oauth_token_url).mock(
            return_value=Response(200, json={"access_token": "at2", "expires_in": 3600})
        )
        await refresh_access_token(settings, "rt-1")
        body = route.calls.last.request.content.decode()
        assert "grant_type=refresh_token" in body
        assert "refresh_token=rt-1" in body

    @respx.mock
    async def test_erro_de_token_levanta(self):
        settings = get_settings()
        respx.post(settings.oauth_token_url).mock(return_value=Response(400, text="invalid_grant"))
        with pytest.raises(RuntimeError, match="400"):
            await refresh_access_token(settings, "rt-ruim")


class TestTokenToCredentials:
    def test_extrai_account_id_do_id_token(self):
        token = {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "id_token": _jwt({"chatgpt_account_id": "acc-jwt"}),
        }
        credentials = token_to_credentials(token)
        assert credentials.account_id == "acc-jwt"
        assert credentials.access_token == "at"
        assert credentials.expires_at > 0

    def test_fallback_account_id(self):
        token = {"access_token": "at", "refresh_token": "rt", "expires_in": 60}
        credentials = token_to_credentials(token, fallback_account_id="acc-fallback")
        assert credentials.account_id == "acc-fallback"
