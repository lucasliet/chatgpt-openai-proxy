"""Rota POST /v1/responses — passthrough da Responses API para o Codex.

O body é encaminhado ao backend e a resposta é relayada, em streaming SSE ou
JSON conforme ``stream``. O backend Codex só aceita ``stream: true``: no modo
não-streaming o proxy faz stream upstream e agrega o objeto ``response`` do
evento ``response.completed`` antes de responder.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..converters.streams import aggregate_responses_events, format_sse
from ..codex import Engine, UpstreamError
from ..database import get_session
from ..deps import AuthContext, require_api_key, require_user_credentials
from ..oauth import Credentials
from .common import upstream_error_response

router = APIRouter()


@router.post("")
async def create_response(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[Credentials, Depends(require_user_credentials)],
):
    engine: Engine = request.app.state.engine
    payload: dict[str, Any] = await request.json()

    if payload.get("stream"):
        return StreamingResponse(
            _sse_relay(engine, credentials, payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Backend exige stream=true: não-streaming agrega via stream upstream.
    payload = {**payload, "stream": True}
    try:
        body = await aggregate_responses_events(
            engine.responses_stream(credentials, payload)
        )
    except UpstreamError as error:
        return upstream_error_response(error)
    if body is None:
        return upstream_error_response(
            UpstreamError(502, "stream encerrada sem response.completed")
        )
    return JSONResponse(body)


async def _sse_relay(engine: Engine, credentials: Credentials, payload: dict[str, Any]):
    async for event in engine.responses_stream(credentials, payload):
        yield format_sse(event)
