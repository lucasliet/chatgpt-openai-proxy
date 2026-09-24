"""Rota POST /v1/responses — passthrough da Responses API para o Codex.

O body é encaminhado ao backend (com ``store: false`` garantido no caso do
chat completions; aqui o body segue como enviado pelo cliente) e a resposta
é relayada, em streaming SSE ou JSON conforme ``stream``.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import Session

from ..converters.streams import format_sse
from ..codex import Engine, UpstreamError
from ..database import get_session
from ..deps import AuthContext, require_api_key, require_credentials
from ..oauth import Credentials
from .common import upstream_error_response

router = APIRouter()


@router.post("")
async def create_response(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
):
    engine: Engine = request.app.state.engine
    payload: dict[str, Any] = await request.json()
    credentials: Credentials = await require_credentials(request, session)

    if payload.get("stream"):
        return StreamingResponse(
            _sse_relay(engine, credentials, payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    try:
        body = await engine.responses(credentials, payload)
    except UpstreamError as error:
        return upstream_error_response(error)
    return JSONResponse(body)


async def _sse_relay(engine: Engine, credentials: Credentials, payload: dict[str, Any]):
    async for event in engine.responses_stream(credentials, payload):
        yield format_sse(event)
