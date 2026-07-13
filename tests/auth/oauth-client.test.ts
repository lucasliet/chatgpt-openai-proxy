import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import {
  buildAuthUrl,
  exchangeCodeForTokens,
  refreshAccessToken,
  toCredentials,
} from "../../src/auth/oauth-client";
import type { TokenResponse } from "../../src/types/credentials";

const sampleToken: TokenResponse = {
  access_token: "access-abc",
  refresh_token: "refresh-xyz",
  expires_in: 3600,
  id_token: "header.eyJjaGF0Z3B0X2FjY291bnRfaWQiOiJvcmctMTIzIn0.sig",
  token_type: "bearer",
};

const originalFetch = globalThis.fetch;

beforeEach(() => {
  process.env.OAUTH_CALLBACK_PORT = "1455";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("oauth-client", () => {
  describe("buildAuthUrl", () => {
    it("contém todos os parâmetros obrigatórios do fluxo Codex", () => {
      const url = new URL(
        buildAuthUrl({ codeVerifier: "verifier-123", state: "state-456" }),
      );

      expect(url.searchParams.get("response_type")).toBe("code");
      expect(url.searchParams.get("client_id")).toBe("app_EMoamEEZ73f0CkXaXp7hrann");
      expect(url.searchParams.get("redirect_uri")).toBe("http://localhost:1455/auth/callback");
      expect(url.searchParams.get("scope")).toBe("offline_access openid profile email");
      expect(url.searchParams.get("state")).toBe("state-456");
      expect(url.searchParams.get("code_challenge_method")).toBe("S256");
      expect(url.searchParams.get("codex_cli_simplified_flow")).toBe("true");
      expect(url.searchParams.get("originator")).toBe("codex_cli_rs");
    });

    it("deriva o code_challenge a partir do verifier (S256)", () => {
      const url = new URL(buildAuthUrl({ codeVerifier: "verifier-123", state: "s" }));

      expect(url.searchParams.get("code_challenge")).not.toBe("verifier-123");
      expect(url.searchParams.get("code_challenge")).toMatch(/^[A-Za-z0-9_-]+$/);
    });

    it("respeita OAUTH_CALLBACK_PORT no redirect_uri", () => {
      process.env.OAUTH_CALLBACK_PORT = "8080";
      const url = new URL(buildAuthUrl({ codeVerifier: "v", state: "s" }));

      expect(url.searchParams.get("redirect_uri")).toBe("http://localhost:8080/auth/callback");
    });
  });

  describe("exchangeCodeForTokens", () => {
    it("envia POST form-encoded com grant_type=authorization_code", async () => {
      const captured = captureFetch(200, sampleToken);

      const result = await exchangeCodeForTokens("the-code", {
        codeVerifier: "verifier-123",
        state: "state-456",
      });

      expect(result).toEqual(sampleToken);
      expect(captured.url).toBe("https://auth.openai.com/oauth/token");
      expect(captured.body.get("grant_type")).toBe("authorization_code");
      expect(captured.body.get("code")).toBe("the-code");
      expect(captured.body.get("code_verifier")).toBe("verifier-123");
      expect(captured.body.get("client_id")).toBe("app_EMoamEEZ73f0CkXaXp7hrann");
    });

    it("lança erro com status e body quando a resposta não é 2xx", async () => {
      captureFetch(400, { error: "invalid_grant" });

      expect(
        exchangeCodeForTokens("bad", { codeVerifier: "v", state: "s" }),
      ).rejects.toThrow(/400/);
    });
  });

  describe("refreshAccessToken", () => {
    it("envia POST com grant_type=refresh_token", async () => {
      const captured = captureFetch(200, sampleToken);

      await refreshAccessToken("refresh-xyz");

      expect(captured.body.get("grant_type")).toBe("refresh_token");
      expect(captured.body.get("refresh_token")).toBe("refresh-xyz");
    });

    it("propaga erro 401 quando o refresh token foi revogado", async () => {
      captureFetch(401, { error: "invalid_grant" });

      expect(refreshAccessToken("revoked")).rejects.toThrow(/401/);
    });
  });

  describe("toCredentials", () => {
    it("extrai o account id do id_token", () => {
      const creds = toCredentials(sampleToken);

      expect(creds.accountId).toBe("org-123");
    });

    it("usa fallback quando não há id_token", () => {
      const { id_token: _omit, ...withoutId } = sampleToken;

      const creds = toCredentials(withoutId, "fallback-account");

      expect(creds.accountId).toBe("fallback-account");
    });

    it("calcula expiresAt como now + expires_in * 1000", () => {
      const before = Date.now();
      const creds = toCredentials({ ...sampleToken, expires_in: 1800 });
      const after = Date.now();

      expect(creds.expiresAt).toBeGreaterThanOrEqual(before + 1800 * 1000);
      expect(creds.expiresAt).toBeLessThanOrEqual(after + 1800 * 1000);
    });

    it("usa string vazia quando não há account id em lugar algum", () => {
      const { id_token: _omit, ...withoutId } = sampleToken;

      const creds = toCredentials(withoutId);

      expect(creds.accountId).toBe("");
    });
  });
});

function captureFetch(status: number, body: unknown) {
  const captured = { url: "", body: new URLSearchParams() };
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  globalThis.fetch = ((url: string, init?: RequestInit) => {
    captured.url = url;
    captured.body = new URLSearchParams(String(init?.body ?? ""));
    return Promise.resolve(response);
  }) as typeof fetch;
  return captured;
}
