"""Rota POST /v1/messages — Anthropic Messages API no Codex.

Aceita o formato da Anthropic (``system``, content blocks, ``tool_use`` /
``tool_result``, ``input_schema``), converte para o pipeline interno de Chat
Completions e devolve a resposta no formato Anthropic — JSON ou streaming SSE
com os eventos oficiais (``message_start``, ``content_block_*``,
``message_delta``, ``message_stop``).

O ``model`` do request é repassado ao upstream como nos demais endpoints —
clientes Anthropic precisam enviar um modelo do ChatGPT Plan.
"""

from contextlib import aclosing
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..codex import Engine, UpstreamError
from ..converters.anthropic import (
    anthropic_to_chat,
    chat_chunks_to_anthropic_events,
    chat_to_anthropic,
    format_anthropic_sse,
)
from ..converters.chat_completions import chat_to_responses, responses_to_chat
from ..converters.streams import (
    aggregate_responses_events,
    responses_events_to_chat_chunks,
)
from ..database import get_session
from ..deps import AuthContext, require_api_key, require_user_credentials
from ..oauth import Credentials
from ..telemetry import tracked_events
from .common import upstream_error_response

router = APIRouter()


@router.post("")
async def create_message(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[Credentials, Depends(require_user_credentials)],
):
    engine: Engine = request.app.state.engine
    body: dict[str, Any] = await request.json()
    model = body.get("model") or ""

    chat = anthropic_to_chat(body)
    chat["model"] = model
    payload = chat_to_responses(chat)

    if body.get("stream"):
        return StreamingResponse(
            _anthropic_stream(
                engine, credentials, payload, model, auth.user.id, auth.user.created_at
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Backend exige stream=true: não-streaming agrega via stream upstream.
    payload["stream"] = True
    try:
        response = await aggregate_responses_events(
            tracked_events(engine, credentials, payload, auth.user.id, auth.user.created_at)
        )
    except UpstreamError as error:
        return upstream_error_response(error)
    if response is None:
        return upstream_error_response(
            UpstreamError(502, "stream encerrada sem response.completed")
        )
    return JSONResponse(chat_to_anthropic(responses_to_chat(response), model))


async def _anthropic_stream(
    engine: Engine,
    credentials: Credentials,
    payload: dict[str, Any],
    model: str,
    user_id: int,
    user_created_at: datetime,
):
    async with aclosing(
        tracked_events(engine, credentials, payload, user_id, user_created_at)
    ) as events:
        chunks = responses_events_to_chat_chunks(events, model)
        async for event_type, data in chat_chunks_to_anthropic_events(chunks, model):
            yield format_anthropic_sse(event_type, data)
