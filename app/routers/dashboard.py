import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlmodel import Session

from ..config import get_settings
from ..database import get_session
from ..deps import require_api_key
from ..models import ApiKey, User
from ..subscription import SubscriptionService
from .dashboard_login import dashboard_route_path, render_dashboard_login
from .login import _login_error
from .subscription_page import render_subscription
from .usage_page import UsagePeriod, render_usage

router = APIRouter()
COOKIE = "dashboard_session"
SESSION_SECONDS = 12 * 3600


def session_signer() -> URLSafeTimedSerializer:
    secret = get_settings().cookie_secret
    if secret == "chatgpt-proxy-dev-secret" or len(secret) < 32:
        raise _login_error(
            "Configure COOKIE_SECRET com um segredo aleatório de pelo menos 32 caracteres para habilitar o dashboard.",
            503,
        )
    return URLSafeTimedSerializer(secret, salt="dashboard-session")


def require_dashboard_user(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> User:
    if not request.cookies.get(COOKIE):
        raise HTTPException(
            status_code=303,
            headers={"Location": dashboard_route_path(request, "dashboard_login_page")},
        )
    try:
        identity = session_signer().loads(request.cookies.get(COOKIE, ""), max_age=SESSION_SECONDS)
        user = session.get(User, identity["id"])
        api_key = session.get(ApiKey, identity["key"])
        if (
            user
            and api_key
            and api_key.user_id == user.id
            and api_key.revoked_at is None
            and user.account_id == identity["account"]
            and user.created_at.isoformat() == identity["created"]
        ):
            return user
    except (BadSignature, KeyError, TypeError, ValueError):
        pass
    raise HTTPException(
        status_code=303, headers={"Location": dashboard_route_path(request, "dashboard_login_page")}
    )


@router.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page(request: Request):
    token = request.session.setdefault("dashboard_csrf", secrets.token_urlsafe(32))
    return HTMLResponse(
        render_dashboard_login(request, token), headers={"Cache-Control": "no-store"}
    )


@router.post("/dashboard/login")
async def dashboard_login_submit(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    signer = session_signer()
    form = await request.form()
    token = form.get("csrf_token")
    expected_token = request.session.get("dashboard_csrf")
    if (
        not isinstance(token, str)
        or not isinstance(expected_token, str)
        or not secrets.compare_digest(token.encode(), expected_token.encode())
    ):
        raise _login_error(
            "Sessão de acesso inválida ou expirada. Atualize a página e tente novamente.", 403
        )
    key = form.get("key")
    try:
        auth = require_api_key(f"Bearer {key.strip()}" if isinstance(key, str) else None, session)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return HTMLResponse(
            render_dashboard_login(request, token, error="API key inválida ou revogada."),
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
    user = auth.user
    request.session.pop("dashboard_csrf", None)
    cookie = signer.dumps(
        {
            "id": user.id,
            "key": auth.api_key.id,
            "account": user.account_id,
            "created": user.created_at.isoformat(),
        }
    )
    response = RedirectResponse(dashboard_route_path(request, "dashboard_page"), status_code=303)
    response.set_cookie(
        COOKIE,
        cookie,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    user: Annotated[User, Depends(require_dashboard_user)],
    session: Annotated[Session, Depends(get_session)],
    days: UsagePeriod = UsagePeriod.WEEK,
):
    return HTMLResponse(
        render_usage(
            session, user, days, admin=False, root_path=request.scope.get("root_path", "")
        ),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/dashboard/logout")
async def dashboard_logout(request: Request):
    response = RedirectResponse(
        dashboard_route_path(request, "dashboard_login_page"), status_code=303
    )
    response.delete_cookie(COOKIE)
    return response


@router.get("/dashboard/limits", response_class=HTMLResponse)
async def dashboard_limits(
    request: Request,
    user: Annotated[User, Depends(require_dashboard_user)],
    session: Annotated[Session, Depends(get_session)],
):
    service: SubscriptionService = request.app.state.subscription
    result = await service.get(user, session)
    return HTMLResponse(render_subscription(result), headers={"Cache-Control": "no-store"})
