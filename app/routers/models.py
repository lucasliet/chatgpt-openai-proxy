"""Rota GET /v1/models — allowlist do ChatGPT Plan."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ..allowlist import list_allowed_models
from ..deps import AuthContext, require_api_key

router = APIRouter()


@router.get("")
async def list_models(auth: Annotated[AuthContext, Depends(require_api_key)]):
    return list_allowed_models()
