"""Rota POST /v1/chat/completions — OpenAI Chat Completions no Codex."""

from contextlib import aclosing
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..codex import Engine, UpstreamError
from ..converters.chat_completions import chat_to_responses, responses_to_chat
from ..converters.streams import (
    DONE_FRAME,
    aggregate_responses_events,
    format_sse,
    responses_events_to_chat_chunks,
)
from ..database import get_session
from ..deps import AuthContext, require_api_key, require_user_credentials
from ..oauth import Credentials
from ..telemetry import tracked_events
from .common import upstream_error_response

router = APIRouter()


@router.post("")
async def create_chat_completion(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[Credentials, Depends(require_user_credentials)],
):
    engine: Engine = request.app.state.engine
    body: dict[str, Any] = await request.json()
    payload = chat_to_responses(body)
    model = body.get("model", "")

    if body.get("stream"):
        return StreamingResponse(
            _chat_stream(engine, credentials, payload, model, auth.user.id, auth.user.created_at),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # O backend Codex só aceita stream=true; no modo não-streaming usamos
    # stream upstream e agregamos o objeto Response completo.
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
    return JSONResponse(responses_to_chat(response))


async def _chat_stream(
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
        async for chunk in responses_events_to_chat_chunks(events, model):
            yield format_sse(chunk)
    yield DONE_FRAME
