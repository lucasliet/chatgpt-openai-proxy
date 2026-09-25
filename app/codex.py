"""Client do backend Codex do ChatGPT Plan com duas engines intercambiáveis.

Ambas implementam a mesma interface:

- ``responses(...)`` — chamada não-streaming; retorna o JSON da Responses API
  e levanta ``UpstreamError`` em erro do backend.
- ``responses_stream(...)`` — chamada streaming; retorna um async iterator de
  eventos da Responses API (dicts), encerrando após ``response.completed``.

Engines:

- ``LiteLLMEngine`` (default): usa ``litellm.aresponses`` com provider
  ``openai/`` + ``api_base`` apontando para o backend Codex, Bearer token do
  OAuth e header ``ChatGPT-Account-Id``.
- ``HttpxEngine``: port fiel do proxy original (Bun/Hono) — POST direto em
  ``{codex_base_url}/responses`` com relay SSE cru.

Selecione via ``UPSTREAM_ENGINE=litellm|httpx``.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

from .config import Settings
from .converters.streams import iter_sse_events
from .oauth import Credentials


class UpstreamError(Exception):
    """Erro do backend Codex, com status HTTP e corpo para relay."""

    def __init__(self, status: int, body: str):
        super().__init__(f"Codex backend error ({status}): {body}")
        self.status = status
        self.body = body


class Engine(Protocol):
    name: str

    async def responses(self, credentials: Credentials, payload: dict[str, Any]) -> dict[str, Any]: ...

    def responses_stream(
        self, credentials: Credentials, payload: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def list_models(self, credentials: Credentials) -> list[str]: ...


def extract_model_ids(data: Any) -> list[str]:
    """Extrai ids de modelo de respostas com formatos distintos do backend.

    Aceita lista de strings, lista de objetos (``id``/``model``/``slug``/
    ``name``) e objetos com chaves ``models``/``data``/``supported_models``.
    """
    if isinstance(data, list):
        ids: list[str] = []
        for item in data:
            ids.extend(extract_model_ids(item))
        return ids
    if isinstance(data, dict):
        for key in ("models", "data", "supported_models", "model_ids"):
            if key in data:
                return extract_model_ids(data[key])
        for key in ("id", "model", "slug", "name"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return [value]
    if isinstance(data, str) and data:
        return [data]
    return []


async def _fetch_model_ids(base_url: str, headers: dict[str, str]) -> list[str]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
    if response.status_code >= 400:
        raise UpstreamError(response.status_code, response.text)
    return extract_model_ids(response.json())


class HttpxEngine:
    """Engine direta via HTTPX — comportamento idêntico ao proxy original."""

    name = "httpx"
    _NON_STREAM_TIMEOUT = 600.0

    def __init__(self, settings: Settings):
        self._base_url = settings.codex_base_url.rstrip("/")

    def _headers(self, credentials: Credentials) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {credentials.access_token}",
            "ChatGPT-Account-Id": credentials.account_id,
        }

    def _url(self) -> str:
        return f"{self._base_url}/responses"

    async def responses(self, credentials: Credentials, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._NON_STREAM_TIMEOUT) as client:
            response = await client.post(
                self._url(), headers=self._headers(credentials), json=payload
            )
        if response.status_code >= 400:
            raise UpstreamError(response.status_code, response.text)
        return response.json()

    async def responses_stream(
        self, credentials: Credentials, payload: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        client = httpx.AsyncClient(timeout=None)
        try:
            request = client.build_request(
                "POST", self._url(), headers=self._headers(credentials), json=payload
            )
            response = await client.send(request, stream=True)
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")
                raise UpstreamError(response.status_code, body)

            completed = False
            async for event in iter_sse_events(response.aiter_bytes()):
                yield event
                if event.get("type") == "response.completed":
                    completed = True
                    break
            if not completed:
                raise UpstreamError(502, "stream encerrada sem response.completed")
        finally:
            await client.aclose()

    async def list_models(self, credentials: Credentials) -> list[str]:
        return await _fetch_model_ids(self._base_url, self._headers(credentials))


class LiteLLMEngine:
    """Engine via LiteLLM (``litellm.aresponses``) — provider openai/ custom."""

    name = "litellm"

    def __init__(self, settings: Settings):
        self._settings = settings
        import litellm

        self._litellm = litellm
        # Mantém o LiteLLM silencioso em produção.
        litellm.set_verbose = False

    def _kwargs(self, credentials: Credentials, payload: dict[str, Any]) -> dict[str, Any]:
        kwargs = {k: v for k, v in payload.items() if k != "model" and v is not None}
        kwargs["model"] = f"openai/{payload['model']}"
        kwargs["api_base"] = self._settings.codex_base_url
        kwargs["api_key"] = credentials.access_token
        kwargs["extra_headers"] = {"ChatGPT-Account-Id": credentials.account_id}
        return kwargs

    @staticmethod
    def _to_dict(event: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            return event
        if hasattr(event, "model_dump"):
            return event.model_dump(exclude_none=True)
        if hasattr(event, "dict"):
            return event.dict()
        import json

        return json.loads(event.model_dump_json()) if hasattr(event, "model_dump_json") else dict(event)

    async def responses(self, credentials: Credentials, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._litellm.aresponses(**self._kwargs(credentials, payload))
        except Exception as exc:  # litellm levanta vários tipos de exceção
            raise _to_upstream_error(exc) from exc
        return self._to_dict(result)

    async def responses_stream(
        self, credentials: Credentials, payload: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs = self._kwargs(credentials, payload)
        kwargs["stream"] = True
        try:
            result = await self._litellm.aresponses(**kwargs)
        except Exception as exc:
            raise _to_upstream_error(exc) from exc

        completed = False
        if hasattr(result, "__aiter__"):
            async for event in result:
                event_dict = self._to_dict(event)
                yield event_dict
                if event_dict.get("type") == "response.completed":
                    completed = True
                    break
        else:
            for event in result:
                event_dict = self._to_dict(event)
                yield event_dict
                if event_dict.get("type") == "response.completed":
                    completed = True
                    break
        if not completed:
            raise UpstreamError(502, "stream encerrada sem response.completed")

    async def list_models(self, credentials: Credentials) -> list[str]:
        headers = {
            "Authorization": f"Bearer {credentials.access_token}",
            "ChatGPT-Account-Id": credentials.account_id,
        }
        return await _fetch_model_ids(self._settings.codex_base_url, headers)


def _to_upstream_error(exc: Exception) -> UpstreamError:
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None) or 502
    return UpstreamError(int(status), str(exc))


def build_engine(settings: Settings) -> Engine:
    """Fabrica a engine upstream conforme ``UPSTREAM_ENGINE``."""
    name = settings.upstream_engine.lower()
    if name == "httpx":
        return HttpxEngine(settings)
    if name == "litellm":
        return LiteLLMEngine(settings)
    raise ValueError(f"UPSTREAM_ENGINE inválido: {settings.upstream_engine!r} (use litellm ou httpx)")
