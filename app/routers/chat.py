"""Rota POST /v1/chat/completions — OpenAI Chat Completions no Codex."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..codex import Engine, UpstreamError
from ..converters.chat_completions import chat_to_responses, responses_to_chat
from ..converters.streams import (
    DONE_FRAME,
    format_sse,
    responses_events_to_chat_chunks,
)
from ..database import get_session
from ..deps import AuthContext, require_api_key, require_user_credentials
from ..oauth import Credentials
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
            _chat_stream(engine, credentials, payload, model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    try:
        response = await engine.responses(credentials, payload)
    except UpstreamError as error:
        return upstream_error_response(error)
    return JSONResponse(responses_to_chat(response))


async def _chat_stream(
    engine: Engine, credentials: Credentials, payload: dict[str, Any], model: str
):
    events = engine.responses_stream(credentials, payload)
    async for chunk in responses_events_to_chat_chunks(events, model):
        yield format_sse(chunk)
    yield DONE_FRAME
