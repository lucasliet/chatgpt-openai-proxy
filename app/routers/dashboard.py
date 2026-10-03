import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlmodel import Session, select

from ..config import get_settings
from ..database import get_session
from ..models import User
from ..oauth import (
    build_auth_url,
    exchange_code_for_tokens,
    generate_code_verifier,
    generate_state,
    token_to_credentials,
)
from .login import (
    CompletePayload,
    _login_error,
    _parse_callback_url,
    _render_login_html,
)
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
        raise HTTPException(status_code=303, headers={"Location": "/dashboard/login"})
    try:
        identity = session_signer().loads(request.cookies.get(COOKIE, ""), max_age=SESSION_SECONDS)
        user = session.get(User, identity["id"])
        if (
            user
            and user.account_id == identity["account"]
            and user.created_at.isoformat() == identity["created"]
        ):
            return user
    except (BadSignature, KeyError, TypeError, ValueError):
        pass
    raise HTTPException(status_code=303, headers={"Location": "/dashboard/login"})


@router.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page():
    return _render_login_html(get_settings().oauth_callback_port, dashboard=True)


@router.post("/dashboard/login/start")
async def dashboard_login_start(request: Request):
    session_signer()
    verifier, state = generate_code_verifier(), generate_state()
    request.session["dashboard_pkce"] = json.dumps({"verifier": verifier, "state": state})
    return {"authUrl": build_auth_url(get_settings(), verifier, state)}


@router.post("/dashboard/login/complete")
async def dashboard_login_complete(
    payload: CompletePayload,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    raw = request.session.pop("dashboard_pkce", None)
    if not raw:
        raise _login_error("Sessão de login expirada. Reinicie o login.")
    parsed = _parse_callback_url(payload.callbackUrl.strip())
    try:
        pkce = json.loads(raw)
        if parsed.get("state") != pkce["state"] or "error" in parsed:
            raise _login_error("Callback inválido ou state mismatch. Reinicie o login.")
        token = await exchange_code_for_tokens(get_settings(), parsed["code"], pkce["verifier"])
        credentials = token_to_credentials(token)
    except (ValueError, KeyError, TypeError):
        raise _login_error("Sessão OAuth inválida. Reinicie o login.") from None
    except HTTPException:
        raise
    except (httpx.HTTPError, RuntimeError):
        raise _login_error(
            "Não foi possível autenticar com o ChatGPT. Reinicie o login.", 502
        ) from None
    user = (
        session.exec(select(User).where(User.account_id == credentials.account_id)).first()
        if credentials.account_id
        else None
    )
    if user is None:
        raise _login_error(
            "Esta conta ChatGPT não está cadastrada no proxy. Nenhuma conta foi criada.",
            403,
        )
    cookie = session_signer().dumps(
        {
            "id": user.id,
            "account": user.account_id,
            "created": user.created_at.isoformat(),
        }
    )
    response = JSONResponse({"dashboard": True})
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
    user: Annotated[User, Depends(require_dashboard_user)],
    session: Annotated[Session, Depends(get_session)],
    days: UsagePeriod = UsagePeriod.WEEK,
):
    return HTMLResponse(
        render_usage(session, user, days, admin=False),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/dashboard/logout")
async def dashboard_logout():
    response = RedirectResponse("/dashboard/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response
