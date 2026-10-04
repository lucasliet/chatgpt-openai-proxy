from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from ..database import get_session
from ..deps import AuthContext, require_api_key
from ..subscription import SubscriptionService

router = APIRouter()


@router.get("")
async def subscription_usage(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
):
    service: SubscriptionService = request.app.state.subscription
    result = await service.get(auth.user, session)
    return JSONResponse(
        result.model_dump(mode="json"),
        status_code=200 if result.available else 503,
        headers={"Cache-Control": "no-store"},
    )
