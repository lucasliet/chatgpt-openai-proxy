import { afterAll, beforeAll, beforeEach, describe, expect, it } from "bun:test";
import { Hono } from "hono";
import { loginRoutes } from "../../../src/server/auth/login-routes";
import type { Credentials, TokenResponse } from "../../../src/types/credentials";

const ENV_KEYS = ["CHATGPT_PROXY_HOME", "CHATGPT_ACCESS_TOKEN", "CHATGPT_REFRESH_TOKEN", "CHATGPT_ACCOUNT_ID", "CHATGPT_EXPIRES_AT"] as const;
const savedEnv: Record<string, string | undefined> = {};
let persisted: Credentials | null = null;

beforeAll(() => {
  for (const key of ENV_KEYS) savedEnv[key] = process.env[key];
});

beforeEach(() => {
  for (const key of ENV_KEYS) delete process.env[key];
  process.env.CHATGPT_PROXY_HOME = "/tmp/cgp-login-routes-unused";
  process.env.COOKIE_SECRET = "test-secret";
  persisted = null;
});

afterAll(() => {
  for (const key of ENV_KEYS) {
    if (savedEnv[key] === undefined) delete process.env[key];
    else process.env[key] = savedEnv[key];
  }
});

const sampleToken: TokenResponse = {
  access_token: "access-web",
  refresh_token: "refresh-web",
  expires_in: 3600,
  id_token: "header.eyJjaGF0Z3B0X2FjY291bnRfaWQiOiJvcmctd2ViIn0.sig",
  token_type: "bearer",
};

function buildApp(
  options: {
    exchangeResult?: () => Promise<TokenResponse>;
    exchangeThrows?: Error;
  } = {},
) {
  const exchange = options.exchangeThrows
    ? async () => {
        throw options.exchangeThrows;
      }
    : async () => options.exchangeResult?.() ?? sampleToken;

  const app = new Hono();
  app.route("/login", loginRoutes({
    exchange: exchange as never,
    persist: async (c) => {
      persisted = c;
    },
  }));
  return app;
}

async function startLogin(app: Hono): Promise<{ authUrl: string; cookie: string; state: string }> {
  const resp = await app.request("/login/start", { method: "POST" });
  const body = (await resp.json()) as { authUrl: string };
  const setCookie = resp.headers.get("set-cookie") ?? "";
  const cookie = setCookie.split(";")[0] ?? "";
  const state = new URL(body.authUrl).searchParams.get("state") ?? "";
  return { authUrl: body.authUrl, cookie, state };
}

function buildCallbackUrl(state: string, code = "the-code"): string {
  return `http://localhost:1455/auth/callback?code=${code}&state=${state}`;
}

describe("login-routes", () => {
  describe("GET /login", () => {
    it("retorna HTML 200 com Content-Type text/html", async () => {
      const app = buildApp();

      const resp = await app.request("/login");

      expect(resp.status).toBe(200);
      expect(resp.headers.get("Content-Type")).toContain("text/html");
    });

    it("contém o título ChatGPT na página", async () => {
      const app = buildApp();

      const resp = await app.request("/login");
      const body = await resp.text();

      expect(body).toContain("ChatGPT");
    });
  });

  describe("POST /login/start", () => {
    it("retorna authUrl com todos os parâmetros obrigatórios do fluxo Codex", async () => {
      const app = buildApp();

      const { authUrl } = await startLogin(app);

      expect(authUrl).toContain("https://auth.openai.com/oauth/authorize");
      expect(authUrl).toContain("client_id=app_EMoamEEZ73f0CkXaXp7hrann");
      expect(authUrl).toContain("code_challenge_method=S256");
      expect(authUrl).toContain("originator=codex_cli_rs");
      expect(authUrl).toContain("codex_cli_simplified_flow=true");
    });

    it("seta cookie pkce httpOnly", async () => {
      const app = buildApp();

      const { cookie } = await startLogin(app);

      expect(cookie.startsWith("pkce=")).toBe(true);
    });

    it("gera state distinto a cada chamada", async () => {
      const app = buildApp();

      const { state: s1 } = await startLogin(app);
      const { state: s2 } = await startLogin(app);

      expect(s1).not.toBe(s2);
    });
  });

  describe("POST /login/complete (happy path)", () => {
    it("conclui login com callbackUrl válida + cookie correto", async () => {
      const app = buildApp();
      const { cookie, state } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: buildCallbackUrl(state) }),
      });

      expect(resp.status).toBe(200);
      const body = (await resp.json()) as { success: boolean; accountId: string };
      expect(body.success).toBe(true);
      expect(body.accountId).toBe("org-web");
    });

    it("persiste as credentials resultantes", async () => {
      const app = buildApp();
      const { cookie, state } = await startLogin(app);

      await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: buildCallbackUrl(state) }),
      });

      expect(persisted).not.toBeNull();
      expect(persisted!.accessToken).toBe("access-web");
      expect(persisted!.accountId).toBe("org-web");
    });

    it("limpa o cookie pkce após sucesso", async () => {
      const app = buildApp();
      const { cookie, state } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: buildCallbackUrl(state) }),
      });

      const setCookie = resp.headers.get("set-cookie") ?? "";
      expect(setCookie).toContain("pkce=");
      expect(setCookie.toLowerCase()).toMatch(/max-age=0|expires=thu, 01 jan 1970/);
    });
  });

  describe("POST /login/complete (erros)", () => {
    it("retorna 400 quando não há cookie pkce (sessão expirada)", async () => {
      const app = buildApp();

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callbackUrl: buildCallbackUrl("any") }),
      });

      expect(resp.status).toBe(400);
      const body = (await resp.json()) as { error: { message: string } };
      expect(body.error.message).toContain("expirada");
    });

    it("retorna 400 quando state diverge do cookie (CSRF)", async () => {
      const app = buildApp();
      const { cookie } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: buildCallbackUrl("wrong-state") }),
      });

      expect(resp.status).toBe(400);
      const body = (await resp.json()) as { error: { message: string } };
      expect(body.error.message).toContain("State mismatch");
    });

    it("retorna 400 quando a callback URL contém error do provedor", async () => {
      const app = buildApp();
      const { cookie, state } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: `http://localhost:1455/auth/callback?error=access_denied&state=${state}` }),
      });

      expect(resp.status).toBe(400);
      const body = (await resp.json()) as { error: { message: string } };
      expect(body.error.message).toContain("access_denied");
    });

    it("retorna 400 quando a callback URL não tem code/state", async () => {
      const app = buildApp();
      const { cookie } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: "http://localhost:1455/auth/callback" }),
      });

      expect(resp.status).toBe(400);
      const body = (await resp.json()) as { error: { message: string } };
      expect(body.error.message).toContain("faltam");
    });

    it("retorna 400 quando a callback URL é malformada", async () => {
      const app = buildApp();
      const { cookie } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: "não é uma url" }),
      });

      expect(resp.status).toBe(400);
      const body = (await resp.json()) as { error: { message: string } };
      expect(body.error.message).toContain("inválida");
    });

    it("retorna 400 quando o exchange lança erro", async () => {
      const app = buildApp({ exchangeThrows: new Error("Token request failed (400)") });
      const { cookie, state } = await startLogin(app);

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: cookie },
        body: JSON.stringify({ callbackUrl: buildCallbackUrl(state) }),
      });

      expect(resp.status).toBe(400);
      const body = (await resp.json()) as { error: { message: string } };
      expect(body.error.message).toContain("Falha na troca");
      expect(persisted).toBeNull();
    });

    it("retorna 400 quando body não traz callbackUrl", async () => {
      const app = buildApp();

      const resp = await app.request("/login/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      expect(resp.status).toBe(400);
    });
  });
});
