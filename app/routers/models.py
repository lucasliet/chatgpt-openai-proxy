"""Rota GET /v1/models — lista dinâmica do backend Codex com fallback.

Tenta ``GET {codex_base_url}/models`` com a credencial OAuth do usuário da
API key. Se o backend não suportar listagem (ou o usuário não tiver
credencial válida), cai na allowlist estática de [app/allowlist.py].
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from ..allowlist import list_allowed_models
from ..codex import Engine
from ..config import get_settings
from ..credentials import get_valid_user_credentials
from ..database import get_session
from ..deps import AuthContext, require_api_key

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_model_list(model_ids: list[str]) -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": 1_700_000_000,
                "owned_by": "chatgpt-plan",
            }
            for model_id in model_ids
        ],
    }


@router.get("")
async def list_models(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
):
    engine: Engine = request.app.state.engine
    settings = get_settings()

    try:
        credentials = await get_valid_user_credentials(session, auth.user, settings)
        if credentials is not None:
            model_ids = await engine.list_models(credentials)
        else:
            logger.info("/v1/models: usuário %s sem credencial; usando allowlist", auth.user.id)
            model_ids = []
    except Exception as exc:
        # Listagem é conveniência: qualquer falha cai na allowlist estática.
        logger.warning("/v1/models: listagem dinâmica falhou (%s); usando allowlist", exc)
        model_ids = []
    if model_ids:
        logger.info("/v1/models: %d modelos do backend Codex", len(model_ids))
        return _format_model_list(model_ids)

    return list_allowed_models()
