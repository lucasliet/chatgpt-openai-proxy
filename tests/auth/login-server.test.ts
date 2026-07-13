import { afterAll, beforeAll, beforeEach, describe, expect, it } from "bun:test";
import { runLoginFlow, type LoginDeps } from "../../src/auth/login-server";
import type { Credentials, TokenResponse } from "../../src/types/credentials";

const ENV_KEYS = ["CHATGPT_PROXY_HOME", "CHATGPT_ACCESS_TOKEN", "CHATGPT_REFRESH_TOKEN", "CHATGPT_ACCOUNT_ID", "CHATGPT_EXPIRES_AT"] as const;
const savedEnv: Record<string, string | undefined> = {};
let persisted: Credentials | null = null;

beforeAll(() => {
  for (const key of ENV_KEYS) savedEnv[key] = process.env[key];
});

beforeEach(() => {
  for (const key of ENV_KEYS) delete process.env[key];
  process.env.CHATGPT_PROXY_HOME = "/tmp/cgp-login-test-unused";
  process.env.OAUTH_CALLBACK_PORT = String(randomPort());
  persisted = null;
});

function randomPort(): number {
  return 20000 + Math.floor(Math.random() * 20000);
}

afterAll(() => {
  for (const key of ENV_KEYS) {
    if (savedEnv[key] === undefined) delete process.env[key];
    else process.env[key] = savedEnv[key];
  }
});

const sampleToken: TokenResponse = {
  access_token: "access-from-flow",
  refresh_token: "refresh-from-flow",
  expires_in: 3600,
  id_token: "header.eyJjaGF0Z3B0X2FjY291bnRfaWQiOiJvcmctZmxvdyJ9.sig",
  token_type: "bearer",
};

interface StartedFlow {
  resultPromise: Promise<Credentials>;
  getState: () => string;
  capturedUrl: () => string;
}

function startFlow(deps: LoginDeps): StartedFlow {
  let url = "";
  const resultPromise = runLoginFlow({
    ...deps,
    onUrl: (received) => {
      url = received;
      deps.onUrl?.(received);
    },
  });
  const capturedUrl = () => url;
  const getState = () => new URL(url).searchParams.get("state") ?? "";
  return { resultPromise, getState, capturedUrl };
}

async function waitForUrl(flow: StartedFlow, retries = 200): Promise<void> {
  for (let i = 0; i < retries; i++) {
    if (flow.capturedUrl()) return;
    await sleep(5);
  }
  throw new Error("OAuth server never produced an authorization URL");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

describe("login-server", () => {
  it("completa o fluxo quando o callback chega com code e state válidos", async () => {
    const flow = startFlow({
      exchange: async () => sampleToken,
      persist: async (creds) => {
        persisted = creds;
      },
      onUrl: () => {},
    });
    await waitForUrl(flow);
    await sleep(30);

    const response = await fetch(
      `http://localhost:${process.env.OAUTH_CALLBACK_PORT}/auth/callback?code=the-code&state=${flow.getState()}`,
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toContain("Login conclu");

    const credentials = await flow.resultPromise;

    expect(credentials.accessToken).toBe("access-from-flow");
    expect(credentials.accountId).toBe("org-flow");
    expect(persisted).toEqual(credentials);
  });

  it("rejeita com erro quando o callback traz error do provedor", async () => {
    const flow = startFlow({
      exchange: async () => sampleToken,
      persist: async () => {},
      onUrl: () => {},
    });
    await waitForUrl(flow);
    await sleep(30);

    const response = await fetch(
      `http://localhost:${process.env.OAUTH_CALLBACK_PORT}/auth/callback?error=access_denied`,
    );

    expect(response.status).toBe(400);
    await expect(flow.resultPromise).rejects.toThrow(/access_denied/);
    expect(persisted).toBeNull();
  });

  it("rejeita quando o state diverge do esperado (proteção CSRF)", async () => {
    const flow = startFlow({
      exchange: async () => sampleToken,
      persist: async () => {},
      onUrl: () => {},
    });
    await waitForUrl(flow);
    await sleep(30);

    const response = await fetch(
      `http://localhost:${process.env.OAUTH_CALLBACK_PORT}/auth/callback?code=the-code&state=wrong-state`,
    );

    expect(response.status).toBe(400);
    await expect(flow.resultPromise).rejects.toThrow(/Invalid state/);
    expect(persisted).toBeNull();
  });

  it("rejeita quando o exchange lança erro", async () => {
    const flow = startFlow({
      exchange: async () => {
        throw new Error("Token request failed (400)");
      },
      persist: async () => {},
      onUrl: () => {},
    });
    await waitForUrl(flow);
    await sleep(30);

    await fetch(
      `http://localhost:${process.env.OAUTH_CALLBACK_PORT}/auth/callback?code=x&state=${flow.getState()}`,
    );

    await expect(flow.resultPromise).rejects.toThrow(/Token exchange failed/);
  });

  it("exibe a URL de autorização via callback onUrl", async () => {
    let capturedUrl = "";
    const flow = startFlow({
      exchange: async () => sampleToken,
      persist: async () => {},
      onUrl: (url) => {
        capturedUrl = url;
      },
    });
    await waitForUrl(flow);
    await sleep(30);

    expect(capturedUrl).toContain("https://auth.openai.com/oauth/authorize");
    expect(capturedUrl).toContain("client_id=app_EMoamEEZ73f0CkXaXp7hrann");
    expect(capturedUrl).toContain("code_challenge_method=S256");
    expect(capturedUrl).toContain("originator=codex_cli_rs");
    expect(capturedUrl).toContain("codex_cli_simplified_flow=true");

    await fetch(
      `http://localhost:${process.env.OAUTH_CALLBACK_PORT}/auth/callback?code=c&state=${flow.getState()}`,
    );
    await flow.resultPromise;
  });
});
