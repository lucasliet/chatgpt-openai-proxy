import { beforeEach, describe, expect, it } from "bun:test";
import { createCodexClient } from "../../src/codex/client";
import type { Credentials } from "../../src/types/credentials";
import type { ResponsesRequest } from "../../src/types/responses";

const credentials: Credentials = {
  accessToken: "access-token",
  refreshToken: "refresh-token",
  accountId: "org-account",
  expiresAt: Date.now() + 3_600_000,
};

const sampleBody: ResponsesRequest = {
  model: "gpt-5.1-codex",
  instructions: "You are a helpful assistant.",
  input: [{ type: "message", role: "user", content: "Hello" }],
  store: false,
};

let lastRequest: { url: string; init: RequestInit } | null = null;

beforeEach(() => {
  lastRequest = null;
});

function mockFetch(status: number, body: unknown) {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
  const stub = ((url: string, init?: RequestInit) => {
    lastRequest = { url, init: init ?? {} };
    return Promise.resolve(response);
  }) as typeof fetch;
  return stub;
}

describe("codex client", () => {
  it("envia POST para o endpoint /responses do Codex", async () => {
    const client = createCodexClient({ fetch: mockFetch(200, { ok: true }) });

    await client.createResponse(credentials, sampleBody);

    expect(lastRequest?.url).toBe("https://chatgpt.com/backend-api/codex/responses");
    expect(lastRequest?.init.method).toBe("POST");
  });

  it("inclui o bearer token e o header ChatGPT-Account-Id", async () => {
    const client = createCodexClient({ fetch: mockFetch(200, { ok: true }) });

    await client.createResponse(credentials, sampleBody);

    const headers = new Headers(lastRequest?.init.headers as Record<string, string> | undefined);
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.get("ChatGPT-Account-Id")).toBe("org-account");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("serializa o body Responses API como JSON", async () => {
    const client = createCodexClient({ fetch: mockFetch(200, { ok: true }) });

    await client.createResponse(credentials, sampleBody);

    expect(JSON.parse(String(lastRequest?.init.body))).toEqual(sampleBody);
  });

  it("repassa a Response do fetch sem modificação (incluindo streams)", async () => {
    const client = createCodexClient({ fetch: mockFetch(200, { ok: true }) });

    const response = await client.createResponse(credentials, sampleBody);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
  });
});
