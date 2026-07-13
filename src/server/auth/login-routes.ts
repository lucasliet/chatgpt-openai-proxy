import { Hono } from "hono";
import { deleteCookie, getSignedCookie, setSignedCookie } from "hono/cookie";
import { config } from "../../config";
import { exchangeCodeForTokens, toCredentials } from "../../auth/oauth-client";
import { buildAuthUrl } from "../../auth/oauth-client";
import { generateCodeVerifier, generateState } from "../../auth/pkce";
import { saveCredentials } from "../../auth/token-store";
import type { Credentials, TokenResponse } from "../../types/credentials";

const PKCE_COOKIE = "pkce";
const COOKIE_MAX_AGE = 300;

interface PkceCookiePayload {
  verifier: string;
  state: string;
}

export interface LoginRoutesDeps {
  exchange?: typeof exchangeCodeForTokens;
  persist?: typeof saveCredentials;
}

interface LoginContext {
  Variables: {
    deps: Required<LoginRoutesDeps>;
  };
}

/**
 * Builds the Hono sub-router exposing the web login UI and the PKCE-backed
 * start/complete endpoints. Allows headless/Docker deployments to authenticate
 * by pasting the OAuth callback URL into a browser form.
 */
export function loginRoutes(deps: LoginRoutesDeps = {}): Hono<LoginContext> {
  const app = new Hono<LoginContext>();
  const exchange = deps.exchange ?? exchangeCodeForTokens;
  const persist = deps.persist ?? saveCredentials;

  app.get("/", (c) => c.html(renderLoginHtml()));

  app.post("/start", async (c) => {
    const verifier = generateCodeVerifier();
    const state = generateState();
    const authUrl = buildAuthUrl({ codeVerifier: verifier, state });

    await setSignedCookie(c, PKCE_COOKIE, JSON.stringify({ verifier, state } satisfies PkceCookiePayload), config.cookieSecret, {
      httpOnly: true,
      maxAge: COOKIE_MAX_AGE,
      sameSite: "Lax",
      path: "/login",
    });

    return c.json({ authUrl });
  });

  app.post("/complete", async (c) => {
    const body = (await c.req.json().catch(() => null)) as { callbackUrl?: string } | null;
    if (!body?.callbackUrl) {
      return c.json(errorPayload("Campo callbackUrl é obrigatório."), 400);
    }

    const cookieRaw = await getSignedCookie(c, config.cookieSecret, PKCE_COOKIE);
    if (!cookieRaw) {
      return c.json(errorPayload("Sessão de login expirada. Clique em Iniciar login novamente."), 400);
    }

    let payload: PkceCookiePayload;
    try {
      payload = JSON.parse(cookieRaw) as PkceCookiePayload;
    } catch {
      return c.json(errorPayload("Sessão de login corrompida. Reinicie o fluxo."), 400);
    }

    const parsed = parseCallbackUrl(body.callbackUrl);
    if ("error" in parsed) {
      deleteCookie(c, PKCE_COOKIE, { path: "/login" });
      return c.json(errorPayload(parsed.error), 400);
    }

    if (parsed.state !== payload.state) {
      return c.json(errorPayload("State mismatch — possível CSRF. Reinicie o fluxo."), 400);
    }

    let token: TokenResponse;
    try {
      token = await exchange(parsed.code, { codeVerifier: payload.verifier, state: payload.state });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      return c.json(errorPayload(`Falha na troca do código: ${message}`), 400);
    }

    const credentials: Credentials = toCredentials(token);
    await persist(credentials);
    deleteCookie(c, PKCE_COOKIE, { path: "/login" });

    return c.json({
      success: true,
      accountId: maskAccountId(credentials.accountId),
      expiresAt: credentials.expiresAt,
    });
  });

  return app;
}

function parseCallbackUrl(raw: string): { code: string; state: string } | { error: string } {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { error: "URL de callback inválida: formato não reconhecido." };
  }
  const errorParam = url.searchParams.get("error");
  if (errorParam) {
    const description = url.searchParams.get("error_description");
    return { error: description ? `${errorParam}: ${description}` : errorParam };
  }
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code || !state) {
    return { error: "URL de callback inválida: faltam parâmetros code ou state." };
  }
  return { code, state };
}

function errorPayload(message: string) {
  return { error: { message, type: "login_error" } };
}

function maskAccountId(accountId: string): string {
  if (accountId.length <= 8) return accountId;
  return `${accountId.slice(0, 4)}...${accountId.slice(-4)}`;
}

function renderLoginHtml(): string {
  return `<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Login</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f1117;
      color: #e6e6e6;
      margin: 0;
      padding: 2rem 1rem;
      display: flex;
      justify-content: center;
      min-height: 100vh;
      box-sizing: border-box;
    }
    .container { max-width: 640px; width: 100%; }
    h1 { font-size: 1.5rem; margin: 0 0 0.5rem; }
    p.muted { color: #8a8a8a; margin: 0 0 1.5rem; font-size: 0.9rem; }
    button, .btn {
      display: inline-block;
      background: #4c9ed9;
      color: #fff;
      border: none;
      padding: 0.7rem 1.2rem;
      border-radius: 6px;
      font-size: 0.95rem;
      cursor: pointer;
      text-decoration: none;
      font-family: inherit;
    }
    button:hover, .btn:hover { background: #5fb0e8; }
    button:disabled { background: #2a3a4a; cursor: not-allowed; }
    input[type="text"] {
      width: 100%;
      background: #1a1d27;
      border: 1px solid #333;
      color: #e6e6e6;
      padding: 0.7rem;
      border-radius: 6px;
      font-size: 0.9rem;
      font-family: monospace;
      box-sizing: border-box;
    }
    .hidden { display: none; }
    .step { margin: 1rem 0; padding: 1rem; background: #1a1d27; border-radius: 8px; }
    .step ol { margin: 0.5rem 0; padding-left: 1.4rem; }
    .step li { margin: 0.3rem 0; line-height: 1.5; }
    .step a.btn { margin: 0.5rem 0; word-break: break-all; font-size: 0.85rem; }
    .status { margin-top: 1rem; padding: 0.8rem; border-radius: 6px; font-size: 0.9rem; }
    .status.ok { background: #1a3a1a; color: #7dd87d; }
    .status.err { background: #3a1a1a; color: #e87d7d; }
    label { display: block; margin-bottom: 0.4rem; font-size: 0.85rem; color: #aaa; }
    .actions { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
  </style>
</head>
<body>
  <div class="container">
    <h1>ChatGPT Proxy — Login</h1>
    <p class="muted">Autentique com sua conta ChatGPT para liberar os modelos do Codex Plan.</p>

    <button id="startBtn" onclick="startLogin()">Iniciar login com ChatGPT</button>

    <div id="step2" class="step hidden">
      <ol>
        <li>Abra o link abaixo e autorize o acesso no ChatGPT.</li>
        <li>Ao final, o navegador tentará abrir <code>localhost:1455/...</code> e pode mostrar erro — <strong>isso é normal em Docker/remoto</strong>.</li>
        <li>Copie a <strong>URL completa</strong> da barra de endereços do navegador.</li>
        <li>Cole a URL no campo abaixo e clique em Concluir.</li>
      </ol>
      <a id="authLink" class="btn" target="_blank" rel="noopener">Abrir página de autorização ↗</a>
    </div>

    <div id="step3" class="step hidden">
      <label for="callbackInput">Cole a URL de callback (localhost:1455/auth/callback?code=...)</label>
      <input id="callbackInput" type="text" placeholder="http://localhost:1455/auth/callback?code=...&state=...">
      <div class="actions">
        <button id="completeBtn" onclick="completeLogin()">Concluir login</button>
      </div>
    </div>

    <div id="status" class="status hidden"></div>
  </div>

  <script>
    async function startLogin() {
      const btn = document.getElementById('startBtn');
      btn.disabled = true;
      btn.textContent = 'Gerando URL...';
      try {
        const resp = await fetch('/login/start', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error?.message || 'Erro');
        document.getElementById('authLink').href = data.authUrl;
        document.getElementById('step2').classList.remove('hidden');
        document.getElementById('step3').classList.remove('hidden');
        btn.textContent = 'URL gerada ✓';
      } catch (e) {
        showStatus(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Iniciar login com ChatGPT';
      }
    }

    async function completeLogin() {
      const callbackUrl = document.getElementById('callbackInput').value.trim();
      if (!callbackUrl) { showStatus('Cole a URL de callback.', 'err'); return; }
      const btn = document.getElementById('completeBtn');
      btn.disabled = true;
      btn.textContent = 'Validando...';
      try {
        const resp = await fetch('/login/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ callbackUrl })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error?.message || 'Erro');
        showStatus('Login concluído! Account: ' + (data.accountId || '?') + '. Você já pode usar o proxy.', 'ok');
        document.getElementById('step2').classList.add('hidden');
        document.getElementById('step3').classList.add('hidden');
      } catch (e) {
        showStatus(e.message, 'err');
        btn.disabled = false;
        btn.textContent = 'Concluir login';
      }
    }

    function showStatus(msg, kind) {
      const el = document.getElementById('status');
      el.textContent = msg;
      el.className = 'status ' + kind;
    }
  </script>
</body>
</html>`;
}
