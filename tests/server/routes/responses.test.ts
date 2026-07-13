import { describe, expect, it } from "bun:test";
import { Hono } from "hono";
import { ensureToken } from "../../../src/server/middleware/ensure-token";
import { responsesRoutes } from "../../../src/server/routes/responses";
import type { CodexClient } from "../../../src/codex/client";
import type { Credentials } from "../../../src/types/credentials";

const credentials: Credentials = {
  accessToken: "a",
  refreshToken: "r",
  accountId: "org",
  expiresAt: Date.now() + 3_600_000,
};

function buildApp(
  createResponse: CodexClient["createResponse"],
  loader: () => Promise<{ credentials: Credentials; source: "env" | "file" } | null> = async () => ({
    credentials,
    source: "env",
  }),
): Hono {
  const app = new Hono();
  app.use("*", ensureToken({ loader }));
  app.route("/v1/responses", responsesRoutes({ createResponse }));
  return app;
}

describe("POST /v1/responses (passthrough)", () => {
  it("repassa o body não-stream do Codex sem modificação", async () => {
    const upstreamBody = { id: "resp_1", object: "response", output: [], usage: { input_tokens: 0, output_tokens: 0 } };
    let receivedBody: unknown;
    const app = buildApp(async (_c, body) => {
      receivedBody = body;
      return new Response(JSON.stringify(upstreamBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const response = await app.request("/v1/responses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-5.1-codex",
        input: [{ type: "message", role: "user", content: "hi" }],
        store: false,
      }),
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(upstreamBody);
    expect(receivedBody).toMatchObject({ model: "gpt-5.1-codex", store: false });
  });

  it("repassa erros do Codex com o status original", async () => {
    const app = buildApp(async () => new Response('{"detail":" Instructions are not valid"}', { status: 400 }));

    const response = await app.request("/v1/responses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-5.1-codex", input: [], store: false }),
    });

    expect(response.status).toBe(400);
    const body = (await response.json()) as { error: { type: string } };
    expect(body.error.type).toBe("upstream_error");
  });

  it("retorna 401 quando não há credentials", async () => {
    const app = buildApp(async () => new Response("ok"), async () => null);

    const response = await app.request("/v1/responses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-5.1-codex", input: [], store: false }),
    });

    expect(response.status).toBe(401);
  });

  it("faz pipe do stream do Codex quando stream=true", async () => {
    const encoder = new TextEncoder();
    const upstreamStream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"response.created"}\n\n'));
        controller.close();
      },
    });
    const app = buildApp(async () =>
      new Response(upstreamStream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    const response = await app.request("/v1/responses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-5.1-codex", input: [], store: false, stream: true }),
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("text/event-stream");
    expect(await response.text()).toContain("response.created");
  });
});
