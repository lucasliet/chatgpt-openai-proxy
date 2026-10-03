"""Logout / exclusão de conta — prefixo /logout.

``GET /logout`` renderiza a página de confirmação onde o usuário cola a
própria API key — mesmo design system das páginas ``/`` e ``/login``
(``app/routers/theme.py``). ``POST /logout`` exige autenticação via Bearer
API key (a mesma dependency das rotas de proxy) e remove **permanentemente**
a conta do proxy: todas as API keys do usuário e a linha do usuário, apagando
junto os tokens OAuth da conta ChatGPT. A exclusão é imediata — a key usada
na requisição passa a retornar 401 — e é irreversível: para voltar, basta se
cadastrar de novo em ``/login``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..database import get_session
from ..deps import AuthContext, require_api_key
from ..models import ApiKey
from .theme import (
    BASE_CSS,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
)

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def logout_page():
    return _render_logout_html()


@router.post("")
def logout(
    auth: Annotated[AuthContext, Depends(require_api_key)],
    session: Annotated[Session, Depends(get_session)],
):
    user = auth.user
    for api_key in session.exec(select(ApiKey).where(ApiKey.user_id == user.id)).all():
        session.delete(api_key)
    session.delete(user)
    session.commit()
    return {
        "success": True,
        "message": "Conta, credenciais e API keys removidas. Você pode se cadastrar novamente em /login.",
    }


_PAGE_CSS = """
.step p { margin: 0 0 0.8rem; font-size: 0.92rem; }
.actions { display: flex; gap: 0.5rem; margin-top: 0.6rem; }
.warning {
  margin: 1rem 0;
  padding: 1rem 1.1rem;
  background: var(--err-bg);
  border: 1px solid var(--danger);
  border-left-width: 3px;
  border-radius: var(--radius);
  color: var(--err-ink);
  font-size: 0.92rem;
  line-height: 1.5;
}
.status:not(.hidden) { animation: rise 220ms var(--ease-out); }
"""


def _render_logout_html() -> str:
    return (
        """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Logout / Excluir conta</title>
  """
        + THEME_HEAD_SCRIPT
        + """<style>"""
        + BASE_CSS
        + _PAGE_CSS
        + THEME_TOGGLE_CSS
        + """</style>
</head>
<body>
  <div class="container narrow">
    <header class="topbar">
      <a class="brand" href="/">chatgpt-openai-proxy</a>
      <nav><a href="/">← documentação</a>"""
        + THEME_TOGGLE_HTML
        + """</nav>
    </header>

    <div class="rise" style="--d: 0">
      <p class="eyebrow"><span class="tick">///</span> LOGOUT</p>
      <h1>Excluir conta</h1>
      <p class="muted">Remova permanentemente sua conta do proxy.</p>
    </div>

    <div class="warning rise" style="--d: 1">
      Esta operação é <strong>irreversível</strong>: ela remove do proxy o seu usuário, as
      credenciais OAuth da sua conta ChatGPT e <strong>todas as suas API keys</strong>.
      A API key deixa de funcionar <strong>na hora</strong>. Para usar o proxy novamente,
      basta se cadastrar de novo em <a href="/login">/login</a>.
    </div>

    <div class="panel step rise" style="--d: 2">
      <p>Cole abaixo a sua API key (a mesma gerada no /login, começa com <code>sk-</code>)
      e confirme a exclusão da conta.</p>
      <label for="apiKeyInput">API key</label>
      <input id="apiKeyInput" type="password" autocomplete="off" placeholder="sk-...">
      <div class="actions">
        <button class="btn danger" id="logoutBtn" onclick="deleteAccount()">Excluir minha conta</button>
      </div>
    </div>

    <div id="status" class="status hidden"></div>

    <footer class="footer">
      <span>chatgpt-openai-proxy</span>
      <span><a href="/login">/login</a> · <a href="/health">/health</a></span>
    </footer>
  </div>

  <script>
    async function deleteAccount() {
      const apiKey = document.getElementById('apiKeyInput').value.trim();
      if (!apiKey) { showStatus('Cole sua API key para continuar.', 'err'); return; }
      if (!confirm('Tem certeza? Essa ação remove permanentemente sua conta, credenciais OAuth e todas as API keys do proxy.')) return;
      const btn = document.getElementById('logoutBtn');
      btn.disabled = true;
      btn.textContent = 'Removendo...';
      try {
        const resp = await fetch('/logout', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + apiKey }
        });
        const text = await resp.text();
        let data;
        try { data = JSON.parse(text); } catch (parseErr) {
          throw new Error('Resposta inesperada do servidor (HTTP ' + resp.status + '). Tente novamente em instantes.');
        }
        if (!resp.ok) throw new Error(data.error?.message || 'Erro');
        showStatus(data.message || 'Conta removida com sucesso. Para usar o proxy novamente, cadastre-se em /login.', 'ok');
        document.getElementById('apiKeyInput').value = '';
        btn.textContent = 'Conta excluída';
      } catch (e) {
        showStatus(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Excluir minha conta';
      }
    }

    function showStatus(msg, kind) {
      const el = document.getElementById('status');
      el.textContent = msg;
      el.className = 'status ' + kind;
    }
  </script>
  """
        + THEME_TOGGLE_SCRIPT
        + """</body>
</html>"""
    )
