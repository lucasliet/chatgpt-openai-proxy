"""Backoffice web — interface HTML para a administração (prima das rotas /admin).

``GET /admin-login`` renderiza o formulário; ``POST /admin-login`` valida a
``ADMIN_API_KEY`` (mesma chave da API JSON) e grava um cookie de sessão admin
assinado (HMAC-SHA256 com ``COOKIE_SECRET``, 12h, httponly, SameSite=Lax).

``/backoffice`` e filhos exigem esse cookie: o guard ``require_admin_session``
redireciona (303) para ``/admin-login`` quando ausente/inválido/expirado. As
ações de escrita reutilizam os handlers da API JSON (``app/routers/admin.py``)
para não divergir em regras de negócio — o cookie substitui o header
``X-Admin-Key`` apenas como meio de autenticação.
"""

import hashlib
import hmac
import html
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..database import get_session
from ..models import ApiKey, User
from ..security import is_admin_key
from . import admin as admin_api
from .theme import (
    BASE_CSS,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
)

router = APIRouter()

ADMIN_COOKIE = "admin_session"
ADMIN_SESSION_MAX_AGE_S = 12 * 3600  # 12h


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _make_admin_cookie(settings: Settings) -> str:
    issued = str(int(time.time()))
    return f"{issued}.{_sign('admin:' + issued, settings.cookie_secret)}"


def _valid_admin_cookie(request: Request, settings: Settings) -> bool:
    raw = request.cookies.get(ADMIN_COOKIE)
    if not raw or "." not in raw:
        return False
    issued, sig = raw.rsplit(".", 1)
    expected = _sign("admin:" + issued, settings.cookie_secret)
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(issued) >= int(time.time()) - ADMIN_SESSION_MAX_AGE_S
    except ValueError:
        return False


def require_admin_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    """Guard das rotas /backoffice: sem sessão admin válida, volta ao login."""
    if not _valid_admin_cookie(request, settings):
        raise HTTPException(
            status_code=303,
            headers={"Location": "/admin-login"},
            detail="Sessão de admin ausente ou expirada.",
        )


backoffice_router = APIRouter(dependencies=[Depends(require_admin_session)])


def _mask(value: str | None) -> str:
    if not value:
        return "—"
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]}"


def _fmt(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M UTC") if dt else "—"


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


# --- /admin-login -----------------------------------------------------------


@router.get("/admin-login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    settings = get_settings()
    if _valid_admin_cookie(request, settings):
        return RedirectResponse("/backoffice", status_code=303)
    return HTMLResponse(_render_login_html())


@router.post("/admin-login", response_class=HTMLResponse)
async def admin_login_submit(request: Request):
    settings = get_settings()
    form = await request.form()
    key = form.get("key")
    if not is_admin_key(settings, key if isinstance(key, str) else None):
        return HTMLResponse(
            _render_login_html(error="Chave de admin inválida."), status_code=401
        )
    response = RedirectResponse("/backoffice", status_code=303)
    response.set_cookie(
        ADMIN_COOKIE,
        _make_admin_cookie(settings),
        max_age=ADMIN_SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
    )
    return response


# --- /backoffice ------------------------------------------------------------


@backoffice_router.get("/backoffice", response_class=HTMLResponse)
async def backoffice_page(request: Request, session: Annotated[Session, Depends(get_session)]):
    ok = request.query_params.get("ok")
    err = request.query_params.get("err")
    return HTMLResponse(_render_dashboard(session, ok=ok, err=err))


@backoffice_router.post("/backoffice/users")
async def backoffice_create_user(request: Request, session: Annotated[Session, Depends(get_session)]):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        return _redirect_with(err="Informe o nome do usuário.")
    try:
        admin_api.create_user(admin_api.UserCreate(name=name), session)
    except HTTPException as exc:
        return _redirect_with(err=_detail_message(exc))
    return _redirect_with(ok=f"Usuário '{name}' criado. Ele ainda precisa fazer /login para conectar a conta ChatGPT.")


@backoffice_router.post("/backoffice/users/{user_id}/delete")
async def backoffice_delete_user(user_id: int, session: Annotated[Session, Depends(get_session)]):
    try:
        admin_api.delete_user(user_id, session)
    except HTTPException as exc:
        return _redirect_with(err=_detail_message(exc))
    return _redirect_with(ok=f"Usuário #{user_id} removido com credenciais e keys.")


@backoffice_router.post("/backoffice/users/{user_id}/keys", response_class=HTMLResponse)
async def backoffice_create_key(
    user_id: int, request: Request, session: Annotated[Session, Depends(get_session)]
):
    form = await request.form()
    label = str(form.get("label", "")).strip()
    try:
        created = admin_api.create_user_key(user_id, admin_api.KeyCreate(label=label), session)
    except HTTPException as exc:
        return _redirect_with(err=_detail_message(exc))
    # A chave completa só existe nesta resposta — renderiza direto (sem PRG)
    # para não vazar em URL/histórico.
    return HTMLResponse(
        _render_dashboard(session, ok=f"Key criada para o usuário #{user_id} — copie agora, ela não será exibida de novo.", new_key=created["key"])
    )


@backoffice_router.post("/backoffice/keys/{key_id}/revoke")
async def backoffice_revoke_key(key_id: int, session: Annotated[Session, Depends(get_session)]):
    try:
        admin_api.revoke_key(key_id, session)
    except HTTPException as exc:
        return _redirect_with(err=_detail_message(exc))
    return _redirect_with(ok=f"Key #{key_id} revogada.")


@backoffice_router.post("/backoffice/logout")
async def backoffice_logout():
    response = RedirectResponse("/admin-login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


def _redirect_with(ok: str | None = None, err: str | None = None) -> RedirectResponse:
    param = f"ok={quote(ok)}" if ok else f"err={quote(err or 'Erro inesperado.')}"
    return RedirectResponse(f"/backoffice?{param}", status_code=303)


def _detail_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("error", {}).get("message", "Erro inesperado."))
    return str(detail)


# --- HTML -------------------------------------------------------------------

_PAGE_CSS = """
table.keys { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 0.5rem 0 0.75rem; }
table.keys th, table.keys td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--line); }
table.keys th { color: var(--muted); font-weight: 500; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; }
.badge { display: inline-block; padding: 0.1rem 0.55rem; border-radius: 999px; font-size: 0.75rem; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.badge.ok { color: var(--ok-ink); border-color: var(--ok-ink); }
.badge.err { color: var(--err-ink); border-color: var(--err-ink); }
.user-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0.5rem; }
.user-head h3 { margin: 0; }
.inline-form { display: inline; }
.inline-form .btn { margin-left: 0.4rem; }
.keyform { display: flex; gap: 0.5rem; margin-top: 0.75rem; flex-wrap: wrap; }
.keyform input { flex: 1; min-width: 200px; }
.btn.small { padding: 0.3rem 0.75rem; font-size: 0.8rem; }
.topbar .btn { margin-left: 1.1rem; }
.user-meta { color: var(--muted); font-size: 0.82rem; margin: 0.15rem 0 0.5rem; }
"""


def _render_login_html(error: str | None = None) -> str:
    status_html = f'<div class="status err">{_esc(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Admin</title>
  {THEME_HEAD_SCRIPT}
  <style>{BASE_CSS}{_PAGE_CSS}{THEME_TOGGLE_CSS}</style>
</head>
<body>
  <div class="container narrow">
    <header class="topbar">
      <a class="brand" href="/">chatgpt-openai-proxy</a>
      <nav><a href="/">← documentação</a>{THEME_TOGGLE_HTML}</nav>
    </header>

    <div class="rise" style="--d: 0">
      <p class="eyebrow"><span class="tick">///</span> BACKOFFICE</p>
      <h1>Acesso de administrador</h1>
      <p class="muted">Entre com a chave de admin (<code>ADMIN_API_KEY</code> do deploy — se não foi definida, ela foi gerada no boot e impressa nos logs do servidor).</p>
    </div>

    <div class="panel rise" style="--d: 1">
      <form method="post" action="/admin-login">
        <label for="key">Chave de admin</label>
        <input id="key" name="key" type="password" autocomplete="current-password" required autofocus>
        <div style="margin-top: 0.75rem"><button class="btn" type="submit">Entrar no backoffice</button></div>
      </form>
      {status_html}
    </div>

    <footer class="footer">
      <span>chatgpt-openai-proxy</span>
      <span><a href="/login">/login</a> · <a href="/health">/health</a></span>
    </footer>
  </div>
  {THEME_TOGGLE_SCRIPT}
</body>
</html>"""


def _credential_badge(user: User) -> str:
    if not user.access_token:
        return '<span class="badge">sem credencial</span>'
    if user.expires_at <= int(time.time() * 1000):
        return '<span class="badge err">token expirado</span>'
    return '<span class="badge ok">autenticado</span>'


def _key_row(key: ApiKey) -> str:
    if key.revoked_at:
        status = f'<span class="badge err">revogada</span>'
        action = ""
    else:
        status = '<span class="badge ok">ativa</span>'
        action = (
            f'<form class="inline-form" method="post" action="/backoffice/keys/{key.id}/revoke"'
            f' onsubmit="return confirm(\'Revogar a key {key.prefix}…?\')">'
            f'<button class="btn small danger" type="submit">Revogar</button></form>'
        )
    return (
        f"<tr><td><code>{_esc(key.prefix)}…</code></td><td>{_esc(key.label) or '—'}</td>"
        f"<td>{_fmt(key.created_at)}</td><td>{_fmt(key.last_used_at)}</td>"
        f"<td>{status}</td><td>{action}</td></tr>"
    )


def _user_panel(user: User, keys: list[ApiKey]) -> str:
    rows = "".join(_key_row(k) for k in keys) or '<tr><td colspan="6" class="muted">Nenhuma key emitida.</td></tr>'
    return f"""
    <div class="panel rise" style="--d: 2">
      <div class="user-head">
        <h3>#{user.id} · {_esc(user.name)}</h3>
        <span>{_credential_badge(user)}
          <form class="inline-form" method="post" action="/backoffice/users/{user.id}/delete"
            onsubmit="return confirm('Remover o usuário #{user.id}, as credenciais OAuth e TODAS as keys?')">
            <button class="btn small danger" type="submit">Excluir usuário</button>
          </form>
        </span>
      </div>
      <p class="user-meta">conta {_esc(_mask(user.account_id))} · criado em {_fmt(user.created_at)} · último login {_fmt(user.last_login_at)}</p>
      <table class="keys">
        <thead><tr><th>key</th><th>label</th><th>criada</th><th>último uso</th><th>status</th><th></th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <form class="keyform" method="post" action="/backoffice/users/{user.id}/keys">
        <input type="text" name="label" placeholder="label da nova key (opcional)">
        <button class="btn small" type="submit">Gerar key</button>
      </form>
    </div>"""


def _render_dashboard(
    session: Session,
    ok: str | None = None,
    err: str | None = None,
    new_key: str | None = None,
) -> str:
    users = session.exec(select(User).order_by(User.id)).all()  # type: ignore[attr-defined]
    all_keys = session.exec(select(ApiKey).order_by(ApiKey.id)).all()  # type: ignore[attr-defined]
    keys_by_user: dict[int, list[ApiKey]] = {}
    for key in all_keys:
        keys_by_user.setdefault(key.user_id, []).append(key)

    status_html = ""
    if ok:
        status_html = f'<div class="status ok">{_esc(ok)}</div>'
    elif err:
        status_html = f'<div class="status err">{_esc(err)}</div>'

    keybox_html = ""
    if new_key:
        keybox_html = f'<div class="keybox">{_esc(new_key)}</div>'

    panels = "".join(_user_panel(u, keys_by_user.get(u.id, [])) for u in users)  # type: ignore[attr-defined]
    if not panels:
        panels = '<div class="panel"><p class="muted">Nenhum usuário ainda — crie o primeiro acima ou peça para alguém fazer <a href="/login">/login</a>.</p></div>'

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Backoffice</title>
  {THEME_HEAD_SCRIPT}
  <style>{BASE_CSS}{_PAGE_CSS}{THEME_TOGGLE_CSS}</style>
</head>
<body>
  <div class="container">
    <header class="topbar">
      <a class="brand" href="/">chatgpt-openai-proxy</a>
      <nav><a href="/">← documentação</a>
        <form class="inline-form" method="post" action="/backoffice/logout"><button class="btn small ghost" type="submit">Sair</button></form>
        {THEME_TOGGLE_HTML}</nav>
    </header>

    <div class="rise" style="--d: 0">
      <p class="eyebrow"><span class="tick">///</span> BACKOFFICE</p>
      <h1>Usuários e API keys</h1>
      <p class="muted">Mesmas operações da API JSON <code>/admin/*</code>, em interface web. A chave completa de uma key só aparece no momento da criação.</p>
    </div>

    <div class="panel rise" style="--d: 1">
      <form class="keyform" method="post" action="/backoffice/users" style="margin-top: 0">
        <input type="text" name="name" placeholder="nome do novo usuário" required>
        <button class="btn small" type="submit">Criar usuário</button>
      </form>
      {status_html}
      {keybox_html}
    </div>

    {panels}

    <footer class="footer">
      <span>chatgpt-openai-proxy</span>
      <span><a href="/">docs</a> · <a href="/health">/health</a></span>
    </footer>
  </div>
  {THEME_TOGGLE_SCRIPT}
</body>
</html>"""
