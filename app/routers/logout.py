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
        "message": "Conta, credenciais, API keys e telemetria removidas. Você pode se cadastrar novamente em /login.",
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
.status:not(.hidden) { animation: rise var(--dur-reveal) var(--ease-out); }
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
      credenciais OAuth da sua conta ChatGPT, <strong>todas as suas API keys</strong> e a telemetria de consumo.
      A API key deixa de funcionar <strong>na hora</strong>. Para usar o proxy novamente,
      basta se cadastrar de novo em <a href="/login">/login</a>.
    </div>

    <div class="panel step rise" style="--d: 2">
      <p>Cole abaixo a sua API key (a mesma gerada no /login, começa com <code>sk-</code>)
      e segure o botão por 2 segundos para confirmar a exclusão.</p>
      <label for="apiKeyInput">API key</label>
      <input id="apiKeyInput" type="password" autocomplete="off" placeholder="sk-...">
      <div class="actions">
        <button type="button" class="btn danger hold" id="logoutBtn" aria-describedby="holdHint">
          <span class="hold-fill" aria-hidden="true"></span>
          <span class="hold-label">Segure para excluir</span>
        </button>
      </div>
      <p id="holdHint" class="muted" style="margin-top: 0.75rem; margin-bottom: 0; font-size: 0.85rem">
        Solte antes dos 2s para cancelar.
      </p>
    </div>

    <div id="status" class="status hidden"></div>

    <footer class="footer">
      <span>chatgpt-openai-proxy</span>
      <span><a href="/login">/login</a> · <a href="/health">/health</a></span>
    </footer>
  </div>

  <script>
    (function setupHoldToDelete() {
      const btn = document.getElementById('logoutBtn');
      const label = btn.querySelector('.hold-label');
      const holdMs = 2000;
      let timer = null;
      let busy = false;

      function clearHold() {
        if (timer) { clearTimeout(timer); timer = null; }
        btn.classList.remove('holding');
      }

      function startHold(e) {
        if (busy || btn.disabled) return;
        if (e.type === 'mousedown' && e.button !== 0) return;
        if (e.cancelable) e.preventDefault();
        const apiKey = document.getElementById('apiKeyInput').value.trim();
        if (!apiKey) { showStatus('Cole sua API key para continuar.', 'err'); return; }
        btn.classList.add('holding');
        timer = setTimeout(function () {
          timer = null;
          btn.classList.remove('holding');
          deleteAccount();
        }, holdMs);
      }

      function cancelHold() {
        if (!timer) return;
        clearHold();
      }

      btn.addEventListener('pointerdown', startHold);
      btn.addEventListener('pointerup', cancelHold);
      btn.addEventListener('pointerleave', cancelHold);
      btn.addEventListener('pointercancel', cancelHold);
      btn.addEventListener('keydown', function (e) {
        if (e.key !== ' ' && e.key !== 'Enter') return;
        if (e.repeat) return;
        startHold(e);
      });
      btn.addEventListener('keyup', function (e) {
        if (e.key === ' ' || e.key === 'Enter') cancelHold();
      });
      btn.addEventListener('blur', cancelHold);

      async function deleteAccount() {
        const apiKey = document.getElementById('apiKeyInput').value.trim();
        if (!apiKey) { showStatus('Cole sua API key para continuar.', 'err'); return; }
        busy = true;
        btn.disabled = true;
        label.textContent = 'Removendo...';
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
          label.textContent = 'Conta excluída';
        } catch (e) {
          showStatus(e.message, 'err');
          btn.disabled = false;
          label.textContent = 'Segure para excluir';
          busy = false;
        }
      }

      function showStatus(msg, kind) {
        const el = document.getElementById('status');
        el.textContent = msg;
        el.className = 'status ' + kind;
      }
    })();
  </script>
  """
        + THEME_TOGGLE_SCRIPT
        + """</body>
</html>"""
    )
