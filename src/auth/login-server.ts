import { config, oauthRedirectUri } from "../config";
import type { Credentials } from "../types/credentials";
import { exchangeCodeForTokens, toCredentials } from "./oauth-client";
import { generateCodeChallenge, generateCodeVerifier, generateState } from "./pkce";
import { saveCredentials } from "./token-store";

const LOGIN_TIMEOUT_MS = 5 * 60 * 1000;
const SUCCESS_HTML = "<!doctype html><html><body><h1>Login conclu&iacute;do</h1><p>Voc&ecirc; pode fechar esta aba.</p></body></html>";
const ERROR_HTML = "<!doctype html><html><body><h1>Falha no login</h1><pre>%MESSAGE%</pre></body></html>";

export interface LoginDeps {
  exchange?: typeof exchangeCodeForTokens;
  persist?: typeof saveCredentials;
  openBrowser?: (url: string) => void;
  onUrl?: (url: string) => void;
}

/**
 * Runs the full OAuth PKCE login flow: spins up a localhost callback server on
 * the Codex-whitelisted port, prints/opens the authorization URL, exchanges the
 * code for tokens, and persists the resulting credentials.
 */
export async function runLoginFlow(deps: LoginDeps = {}): Promise<Credentials> {
  const exchange = deps.exchange ?? exchangeCodeForTokens;
  const persist = deps.persist ?? saveCredentials;
  const codeVerifier = generateCodeVerifier();
  const state = generateState();

  notifyUrl(buildLoginUrl(codeVerifier, state), deps);

  const credentials = await awaitCallback(exchange, codeVerifier, state);
  await persist(credentials);
  return credentials;
}

function buildLoginUrl(codeVerifier: string, state: string): string {
  const challenge = generateCodeChallenge(codeVerifier);
  const url = new URL(config.oauth.authUrl);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.oauth.clientId);
  url.searchParams.set("redirect_uri", oauthRedirectUri());
  url.searchParams.set("scope", config.oauth.scope);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("codex_cli_simplified_flow", "true");
  url.searchParams.set("originator", "codex_cli_rs");
  return url.toString();
}

function notifyUrl(url: string, deps: LoginDeps): void {
  if (deps.onUrl) {
    deps.onUrl(url);
    return;
  }
  if (deps.openBrowser) {
    deps.openBrowser(url);
    return;
  }
  console.log("\nAbra esta URL no navegador para autorizar:\n");
  console.log(url);
  console.log("");
}

function awaitCallback(
  exchange: typeof exchangeCodeForTokens,
  codeVerifier: string,
  expectedState: string,
): Promise<Credentials> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      server?.stop(true);
      reject(new Error("Login timed out after 5 minutes without a callback."));
    }, LOGIN_TIMEOUT_MS);

    const finish = (action: () => void) => {
      clearTimeout(timeout);
      setTimeout(() => {
        server?.stop(true);
        action();
      }, 0);
    };

    let server: ReturnType<typeof Bun.serve> | undefined;
    try {
      server = Bun.serve({
        port: config.oauthCallbackPort,
        hostname: "127.0.0.1",
        async fetch(request) {
          const callbackUrl = new URL(request.url);
          if (callbackUrl.pathname !== "/auth/callback") {
            return new Response("Not found", { status: 404 });
          }

          const code = callbackUrl.searchParams.get("code");
          const state = callbackUrl.searchParams.get("state");
          const error = callbackUrl.searchParams.get("error");

          if (error) {
            finish(() => reject(new Error(`Authorization error: ${error}`)));
            return errorPage(error, 400);
          }

          if (!code || state !== expectedState) {
            finish(() => reject(new Error("Invalid state or missing code.")));
            return errorPage("Invalid state or missing code.", 400);
          }

          try {
            const token = await exchange(code, { codeVerifier, state: expectedState });
            const credentials = toCredentials(token);
            finish(() => resolve(credentials));
            return new Response(SUCCESS_HTML, {
              status: 200,
              headers: { "Content-Type": "text/html; charset=utf-8" },
            });
          } catch (cause) {
            const message = cause instanceof Error ? cause.message : String(cause);
            finish(() => reject(new Error(`Token exchange failed: ${message}`)));
            return errorPage(message, 500);
          }
        },
      });
    } catch (cause) {
      clearTimeout(timeout);
      const message = cause instanceof Error ? cause.message : String(cause);
      reject(new Error(`Failed to start OAuth callback server: ${message}`));
    }
  });
}

function errorPage(message: string, status: number): Response {
  return new Response(ERROR_HTML.replace("%MESSAGE%", escapeHtml(message)), {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
