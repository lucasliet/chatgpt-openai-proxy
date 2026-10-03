"""Fluxo de login web OAuth (PKCE) — uma conta ChatGPT por usuário.

``GET /login`` renderiza a página; ``POST /login/start`` gera verifier/state,
guarda no cookie de sessão assinado (SessionMiddleware) e retorna a URL de
autorização; ``POST /login/complete`` recebe a URL de callback colada pelo
usuário (modo headless/Docker), valida o state e troca o code por tokens.

Ao concluir:

1. O usuário é localizado (ou criado) pelo ``account_id`` do id_token — um
   re-login na mesma conta **renova os tokens** em vez de duplicar.
2. Toda re-login é tratada como recuperação: as API keys antigas da conta são
   **revogadas** e uma **nova key** é gerada e exibida (a chave completa só
   aparece desta vez).

O CSS base vem de ``app/routers/theme.py`` (design system compartilhado);
``_PAGE_CSS`` cobre apenas os blocos específicos do fluxo (steps, keybox).
"""

import json
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..credentials import save_oauth_credentials
from ..database import get_session
from ..models import ApiKey, User, utcnow
from ..oauth import (
    build_auth_url,
    exchange_code_for_tokens,
    generate_code_verifier,
    generate_state,
    parse_jwt_claims,
    token_to_credentials,
)
from ..security import generate_api_key, hash_api_key, key_prefix
from .theme import (
    BASE_CSS,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
)

router = APIRouter()


class CompletePayload(BaseModel):
    callbackUrl: str


def _login_error(message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"message": message, "type": "login_error"}},
    )


def _mask(value: str) -> str:
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]}"


def _display_name(claims: dict | None, account_id: str) -> str:
    email = (claims or {}).get("email")
    if isinstance(email, str) and email:
        return email
    return f"chatgpt-{_mask(account_id)}" if account_id else "chatgpt-user"


@router.get("", response_class=HTMLResponse)
async def login_page(request: Request):
    settings = get_settings()
    return _render_login_html(settings.oauth_callback_port)


@router.post("/start")
async def login_start(request: Request):
    settings = get_settings()
    verifier = generate_code_verifier()
    state = generate_state()
    request.session["pkce"] = json.dumps({"verifier": verifier, "state": state})
    return {"authUrl": build_auth_url(settings, verifier, state)}


@router.post("/complete")
async def login_complete(
    payload: CompletePayload,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
):
    settings: Settings = get_settings()

    raw_cookie = request.session.get("pkce")
    if not raw_cookie:
        raise _login_error("Sessão de login expirada. Clique em Iniciar login novamente.")

    try:
        pkce = json.loads(raw_cookie)
        verifier, expected_state = pkce["verifier"], pkce["state"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise _login_error("Sessão de login corrompida. Reinicie o fluxo.")

    parsed = _parse_callback_url(payload.callbackUrl.strip())
    if "error" in parsed:
        request.session.pop("pkce", None)
        raise _login_error(parsed["error"])

    if parsed["state"] != expected_state:
        raise _login_error("State mismatch — possível CSRF. Reinicie o fluxo.")

    try:
        token = await exchange_code_for_tokens(settings, parsed["code"], verifier)
    except Exception as exc:
        raise _login_error(f"Falha na troca do código: {exc}")

    credentials = token_to_credentials(token)
    if not credentials.account_id:
        raise _login_error("Não foi possível identificar a conta ChatGPT (account_id ausente no id_token).")

    claims = parse_jwt_claims(token.get("id_token", "")) or {}

    # Upsert por account_id: re-login renova tokens sem duplicar usuário.
    user = session.exec(
        select(User).where(User.account_id == credentials.account_id)
    ).first()
    if user is None:
        name = _display_name(claims, credentials.account_id)
        existing = session.exec(select(User).where(User.name == name)).first()
        if existing is not None:
            name = f"{name}-{credentials.account_id[:6]}"
        user = User(name=name, account_id=credentials.account_id)
        session.add(user)
        session.flush()

    save_oauth_credentials(session, user, credentials)

    # Re-login = recuperação: revoga keys antigas e emite uma nova.
    for old_key in session.exec(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))  # type: ignore[attr-defined]
    ).all():
        old_key.revoked_at = utcnow()
        session.add(old_key)

    raw_key = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,  # type: ignore[arg-type]
        label="login",
        prefix=key_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
    )
    session.add(api_key)
    session.commit()

    request.session.pop("pkce", None)

    return {
        "success": True,
        "name": user.name,
        "accountId": _mask(credentials.account_id),
        "expiresAt": credentials.expires_at,
        "apiKey": raw_key,  # exibida apenas desta vez
        "keyPrefix": api_key.prefix,
    }


def _parse_callback_url(raw: str) -> dict[str, str]:
    try:
        parts = urlsplit(raw)
    except ValueError:
        return {"error": "URL de callback inválida: formato não reconhecido."}

    params = parse_qs(parts.query)
    error = params.get("error", [None])[0]
    if error:
        description = params.get("error_description", [None])[0]
        return {"error": f"{error}: {description}" if description else error}

    code = params.get("code", [None])[0]
    state = params.get("state", [None])[0]
    if not code or not state:
        return {"error": "URL de callback inválida: faltam parâmetros code ou state."}
    return {"code": code, "state": state}


_PAGE_CSS = """
.step { animation: rise 260ms var(--ease-out); }
.step ol { margin: 0.5rem 0; padding-left: 1.4rem; }
.step li { margin: 0.3rem 0; }
.step .btn { margin: 0.5rem 0; word-break: break-all; font-size: 0.85rem; }
.actions { display: flex; gap: 0.5rem; margin-top: 0.6rem; }
.keybox { animation: rise 260ms var(--ease-out); }
.status:not(.hidden) { animation: rise 220ms var(--ease-out); }
"""


def _render_login_html(callback_port: int) -> str:
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Login</title>
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
      <p class="eyebrow"><span class="tick">///</span> LOGIN</p>
      <h1>Conecte sua conta ChatGPT</h1>
      <p class="muted">Autorize o proxy a usar a sua assinatura e receba a API key de acesso. Cada login gera uma nova key e revoga as anteriores.</p>
    </div>

    <div class="rise" style="--d: 1">
      <button class="btn" id="startBtn" onclick="startLogin()">Iniciar login com ChatGPT</button>
    </div>

    <div id="step2" class="panel step hidden">
      <ol>
        <li>Abra o link abaixo e autorize o acesso no ChatGPT.</li>
        <li>Quando o navegador mostrar um erro ao tentar abrir <code>localhost:{callback_port}/...</code> (<strong>normal em Docker/remoto</strong>), não feche a aba.</li>
        <li>Copie a <strong>URL completa da barra de endereços</strong> — ela começa com <code>http://localhost:{callback_port}/auth/callback?code=...</code>.</li>
        <li>Cole essa URL no campo abaixo e clique em Concluir.</li>
      </ol>
      <a id="authLink" class="btn ghost" target="_blank" rel="noopener">Abrir página de autorização ↗</a>
    </div>

    <div id="step3" class="panel step hidden">
      <label for="callbackInput">Cole a URL de callback (localhost:{callback_port}/auth/callback?code=...)</label>
      <input id="callbackInput" type="text" placeholder="http://localhost:{callback_port}/auth/callback?code=...&state=...">
      <div class="actions">
        <button class="btn" id="completeBtn" onclick="completeLogin()">Concluir login</button>
      </div>
    </div>

    <div id="status" class="status hidden"></div>
    <div id="apiKeyBox" class="keybox hidden"></div>

    <footer class="footer">
      <span>chatgpt-openai-proxy</span>
      <span><a href="/logout">/logout</a> · <a href="/health">/health</a></span>
    </footer>
  </div>

  <script>
    async function startLogin() {{
      const btn = document.getElementById('startBtn');
      btn.disabled = true;
      btn.textContent = 'Gerando URL...';
      try {{
        const resp = await fetch('/login/start', {{ method: 'POST' }});
        const text = await resp.text();
        let data;
        try {{ data = JSON.parse(text); }} catch (parseErr) {{
          throw new Error('Resposta inesperada do servidor (HTTP ' + resp.status + '). Tente novamente em instantes.');
        }}
        if (!resp.ok) throw new Error(data.error?.message || 'Erro');
        document.getElementById('authLink').href = data.authUrl;
        document.getElementById('step2').classList.remove('hidden');
        document.getElementById('step3').classList.remove('hidden');
        btn.textContent = 'URL gerada ✓';
      }} catch (e) {{
        showStatus(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Iniciar login com ChatGPT';
      }}
    }}

    async function completeLogin() {{
      const callbackUrl = document.getElementById('callbackInput').value.trim();
      if (!callbackUrl) {{ showStatus('Cole a URL de callback.', 'err'); return; }}
      if (callbackUrl.includes('auth.openai.com')) {{
        showStatus('Você colou a URL de autorização (auth.openai.com). Copie a URL da barra de endereços depois que o navegador falhar ao abrir localhost:{callback_port} — ela começa com http://localhost:{callback_port}/auth/callback?code=...', 'err');
        return;
      }}
      if (!callbackUrl.includes('/auth/callback')) {{
        showStatus('A URL precisa conter /auth/callback?code=... Verifique se copiou a URL inteira da barra de endereços.', 'err');
        return;
      }}
      const btn = document.getElementById('completeBtn');
      btn.disabled = true;
      btn.textContent = 'Validando...';
      try {{
        const resp = await fetch('/login/complete', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ callbackUrl }})
        }});
        const text = await resp.text();
        let data;
        try {{ data = JSON.parse(text); }} catch (parseErr) {{
          throw new Error('Resposta inesperada do servidor (HTTP ' + resp.status + '). Tente novamente em instantes.');
        }}
        if (!resp.ok) throw new Error(data.error?.message || 'Erro');
        showStatus('Login concluído! Conta: ' + (data.accountId || '?') + '. Use a API key abaixo no proxy.', 'ok');
        const box = document.getElementById('apiKeyBox');
        box.textContent = data.apiKey;
        box.classList.remove('hidden');
        document.getElementById('step2').classList.add('hidden');
        document.getElementById('step3').classList.add('hidden');
      }} catch (e) {{
        showStatus(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Concluir login';
      }}
    }}

    function showStatus(msg, kind) {{
      const el = document.getElementById('status');
      el.textContent = msg;
      el.className = 'status ' + kind;
    }}
  </script>
  {THEME_TOGGLE_SCRIPT}
</body>
</html>"""
