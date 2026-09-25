"""Testes das engines upstream (seleção, kwargs do LiteLLM, erros httpx)."""

import pytest
import respx
from httpx import Response

from app.codex import (
    HttpxEngine,
    LiteLLMEngine,
    UpstreamError,
    build_engine,
    extract_model_ids,
)
from app.config import Settings, get_settings
from app.oauth import Credentials

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"


def _creds() -> Credentials:
    return Credentials(
        access_token="at-x",
        refresh_token="rt-x",
        account_id="acc-x",
        expires_at=4_000_000_000_000,
    )


class TestBuildEngine:
    def test_default_litellm(self):
        assert build_engine(Settings(upstream_engine="litellm")).name == "litellm"

    def test_httpx(self):
        assert build_engine(Settings(upstream_engine="httpx")).name == "httpx"

    def test_invalido_falha(self):
        with pytest.raises(ValueError):
            build_engine(Settings(upstream_engine="nao-existe"))


class TestLiteLLMEngineKwargs:
    def test_mapeamento_para_codex(self):
        engine = LiteLLMEngine(get_settings())
        payload = {
            "model": "gpt-6-terra",
            "input": [{"type": "message", "role": "user", "content": "oi"}],
            "store": False,
            "instructions": "Seja breve.",
            "stream": None,  # deve ser removido (None)
        }
        kwargs = engine._kwargs(_creds(), payload)
        assert kwargs["model"] == "openai/gpt-6-terra"
        assert kwargs["api_base"] == get_settings().codex_base_url
        assert kwargs["api_key"] == "at-x"
        assert kwargs["extra_headers"] == {"ChatGPT-Account-Id": "acc-x"}
        assert kwargs["store"] is False
        assert "stream" not in kwargs  # None é descartado
        assert "model" not in kwargs or kwargs["model"].startswith("openai/")


@respx.mock
class TestHttpxEngine:
    async def test_responses_ok(self):
        engine = HttpxEngine(get_settings())
        route = respx.post(CODEX_URL).mock(return_value=Response(200, json={"id": "resp_1"}))
        result = await engine.responses(_creds(), {"model": "m", "store": False})
        assert result == {"id": "resp_1"}
        request = route.calls.last.request
        assert request.headers["ChatGPT-Account-Id"] == "acc-x"

    async def test_responses_erro(self):
        engine = HttpxEngine(get_settings())
        respx.post(CODEX_URL).mock(return_value=Response(500, text="boom"))
        with pytest.raises(UpstreamError) as exc_info:
            await engine.responses(_creds(), {"model": "m"})
        assert exc_info.value.status == 500

    async def test_stream_encerra_no_completed(self):
        engine = HttpxEngine(get_settings())
        sse = (
            'data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"x"}\n\n'
            'data: {"type":"response.completed","response":{"id":"r","model":"m","output":[],"usage":{"input_tokens":1,"output_tokens":1}}}\n\n'
            'data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"depois"}\n\n'
        )
        respx.post(CODEX_URL).mock(
            return_value=Response(200, content=sse, headers={"Content-Type": "text/event-stream"})
        )
        events = [e async for e in engine.responses_stream(_creds(), {"model": "m", "stream": True})]
        types = [e["type"] for e in events]
        assert types == ["response.output_text.delta", "response.completed"]

    async def test_stream_erro_status(self):
        engine = HttpxEngine(get_settings())
        respx.post(CODEX_URL).mock(return_value=Response(401, text="unauthorized"))
        with pytest.raises(UpstreamError) as exc_info:
            [e async for e in engine.responses_stream(_creds(), {"model": "m"})]
        assert exc_info.value.status == 401

    async def test_list_models_ok(self):
        engine = HttpxEngine(get_settings())
        route = respx.get(CODEX_MODELS_URL).mock(
            return_value=Response(200, json={"models": ["gpt-6-terra", "gpt-6-luna"]})
        )
        assert await engine.list_models(_creds()) == ["gpt-6-terra", "gpt-6-luna"]
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer at-x"
        assert "client_version" in request.url.params

    async def test_list_models_erro(self):
        engine = HttpxEngine(get_settings())
        respx.get(CODEX_MODELS_URL).mock(return_value=Response(500, text="boom"))
        with pytest.raises(UpstreamError):
            await engine.list_models(_creds())


class TestExtractModelIds:
    def test_lista_de_strings(self):
        assert extract_model_ids(["a", "b"]) == ["a", "b"]

    def test_lista_de_objetos(self):
        assert extract_model_ids([{"id": "a"}, {"slug": "b"}]) == ["a", "b"]

    def test_objeto_com_chaves_conhecidas(self):
        assert extract_model_ids({"data": [{"model": "a"}]}) == ["a"]
        assert extract_model_ids({"supported_models": ["x"]}) == ["x"]

    def test_formato_inesperado_retorna_vazio(self):
        assert extract_model_ids({"foo": 1}) == []
        assert extract_model_ids(None) == []
