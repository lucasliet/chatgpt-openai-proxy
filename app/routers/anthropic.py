"""Rota POST /v1/messages — Anthropic Messages API no Codex.

Aceita o formato da Anthropic (``system``, content blocks, ``tool_use`` /
``tool_result``, ``input_schema``), converte para o pipeline interno de Chat
Completions e devolve a resposta no formato Anthropic — JSON ou streaming SSE
com os eventos oficiais (``message_start``, ``content_block_*``,
``message_delta``, ``message_stop``).

Clientes Anthropic costumam fixar nomes de modelo ``claude-*``; quando o
modelo pedido não está na allowlist do ChatGPT Plan, o ``default_model``
(configurável via env) é usado upstream e o modelo solicitado é ecoado na
resposta para manter a compatibilidade com os clientes.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..allowlist import is_allowed_model
from ..codex import Engine, UpstreamError
from ..config import get_settings
from ..converters.anthropic import (
    anthropic_to_chat,
    chat_chunks_to_anthropic_events,
    chat_to_anthropic,
    format_anthropic_sse,
)
from ..converters.chat_completions import chat_to_responses, responses_to_chat
from ..converters.streams import aggregate_responses_events, responses_events_to_chat_chunks
from ..database import get_session
from ..deps import AuthContext, require_api_key, require_user_credentials
from ..oauth import Credentials
from .common import upstream_error_response

router = APIRouter()


@router.post("")
async def create_message(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[Credentials, Depends(require_user_credentials)],
):
    settings = get_settings()
    engine: Engine = request.app.state.engine
    body: dict[str, Any] = await request.json()

    requested_model = body.get("model") or settings.default_model
    upstream_model = (
        requested_model
        if is_allowed_model(requested_model)
        else settings.default_model
    )

    chat = anthropic_to_chat(body)
    chat["model"] = upstream_model
    payload = chat_to_responses(chat)

    if body.get("stream"):
        return StreamingResponse(
            _anthropic_stream(engine, credentials, payload, requested_model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Backend exige stream=true: não-streaming agrega via stream upstream.
    payload["stream"] = True
    try:
        response = await aggregate_responses_events(
            engine.responses_stream(credentials, payload)
        )
    except UpstreamError as error:
        return upstream_error_response(error)
    if response is None:
        return upstream_error_response(
            UpstreamError(502, "stream encerrada sem response.completed")
        )
    return JSONResponse(chat_to_anthropic(responses_to_chat(response), requested_model))


async def _anthropic_stream(
    engine: Engine, credentials: Credentials, payload: dict[str, Any], model: str
):
    events = engine.responses_stream(credentials, payload)
    chunks = responses_events_to_chat_chunks(events, model)
    async for event_type, data in chat_chunks_to_anthropic_events(chunks, model):
        yield format_anthropic_sse(event_type, data)
