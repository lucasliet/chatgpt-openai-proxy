import html

from fastapi import Request

from .theme import (
    BASE_CSS,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
    favicon_link,
)


def dashboard_route_path(request: Request, route_name: str) -> str:
    """Resolve dashboard navigation within the current app, including named mounts."""
    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}{request.app.url_path_for(route_name)}"


def render_dashboard_login(request: Request, csrf_token: str, error: str | None = None) -> str:
    status = f'<p class="status err" role="alert">{html.escape(error)}</p>' if error else ""
    login_path = html.escape(dashboard_route_path(request, "dashboard_login_submit"), quote=True)
    home_path = html.escape(dashboard_route_path(request, "home_page"), quote=True)
    root_path = html.escape(request.scope.get("root_path", "").rstrip("/"), quote=True)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Consulte seu consumo</title>
  {favicon_link(root_path)}
  {THEME_HEAD_SCRIPT}
  <style>{BASE_CSS}{THEME_TOGGLE_CSS}
    .narrow {{ max-width: 640px; }}
    h1 {{ font-size: clamp(1.8rem, 5vw, 2.5rem); }}
    label {{ display: block; margin-bottom: 0.5rem; font-family: var(--font-mono); }}
    input {{ width: 100%; padding: 0.75rem; border: 1px solid var(--line);
      border-radius: var(--radius); background: var(--surface); color: var(--ink);
      font: inherit; }}
    input:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
    form .btn {{ margin-top: 0.75rem; }}
  </style>
</head>
<body>
  <div class="container narrow">
    <header class="topbar">
      <a class="brand" href="{home_path}">chatgpt-openai-proxy</a>
      <nav><a href="{home_path}">← documentação</a>{THEME_TOGGLE_HTML}</nav>
    </header>
    <div class="rise" style="--d: 0">
      <p class="eyebrow"><span class="tick">///</span> CONSUMO</p>
      <h1>Consulte seu consumo</h1>
      <p class="muted">Informe a API key que você utiliza no proxy para consultar seus dados.</p>
    </div>
    <div class="panel rise" style="--d: 1">
      <form method="post" action="{login_path}">
        <input type="hidden" name="csrf_token" value="{html.escape(csrf_token, quote=True)}">
        <label for="key">Sua API key</label>
        <input id="key" name="key" type="password" autocomplete="off" spellcheck="false" required>
        <button class="btn" type="submit">Consultar consumo</button>
      </form>
      {status}
      <p class="muted">A consulta não cria conta, não altera credenciais e não gera nem revoga API keys.
        A sessão expira em 12 horas; sair dela não exclui sua conta.</p>
    </div>
    <footer class="footer"><span>chatgpt-openai-proxy</span></footer>
  </div>
  {THEME_TOGGLE_SCRIPT}
</body>
</html>"""
