import { describe, expect, it } from "bun:test";
import { Hono } from "hono";
import { ensureToken } from "../../../src/server/middleware/ensure-token";
import { chatCompletionsRoutes } from "../../../src/server/routes/chat-completions";
import type { CodexClient } from "../../../src/codex/client";
import type { Credentials } from "../../../src/types/credentials";

const credentials: Credentials = {
  accessToken: "a",
  refreshToken: "r",
  accountId: "org",
  expiresAt: Date.now() + 3_600_000,
};

function buildApp(upstreamResponses: { status: number; body: unknown; stream?: boolean }): {
  app: Hono;
  lastBody: { value: unknown };
} {
  const lastBody = { value: undefined as unknown };

  const client: CodexClient = {
    async createResponse(_creds, body) {
      lastBody.value = body;
      const raw = body.stream
        ? (upstreamResponses.body as ReadableStream<Uint8Array>)
        : JSON.stringify(upstreamResponses.body);
      return new Response(raw, {
        status: upstreamResponses.status,
        headers: { "Content-Type": body.stream ? "text/event-stream" : "application/json" },
      });
    },
  };

  const app = new Hono();
  app.use("*", ensureToken({ loader: async () => ({ credentials, source: "env" }) }));
  app.route("/v1/chat/completions", chatCompletionsRoutes(client));
  return { app, lastBody };
}

const nonStreamResponse = {
  id: "resp_1",
  object: "response",
  model: "gpt-5.1-codex",
  output: [
    {
      type: "message",
      role: "assistant",
      content: [{ type: "output_text", text: "Olá!" }],
    },
  ],
  usage: { input_tokens: 10, output_tokens: 5 },
};

describe("POST /v1/chat/completions", () => {
  it("converte non-stream response para o formato OpenAI Chat Completions", async () => {
    const { app, lastBody } = buildApp({ status: 200, body: nonStreamResponse });

    const response = await app.request("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "Oi" }],
      }),
    });

    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.object).toBe("chat.completion");
    const choices = body.choices as Record<string, unknown>[];
    expect(choices[0]!.message).toMatchObject({ role: "assistant", content: "Olá!" });
    expect(choices[0]!.finish_reason).toBe("stop");
    expect(lastBody.value).toMatchObject({ store: false, model: "gpt-5.1-codex" });
  });

  it("repassa erro do Codex como erro OpenAI", async () => {
    const { app } = buildApp({ status: 500, body: { detail: "boom" } });

    const response = await app.request("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-5.1-codex", messages: [{ role: "user", content: "x" }] }),
    });

    expect(response.status).toBe(500);
    const body = (await response.json()) as { error: { type: string; message: string } };
    expect(body.error.type).toBe("upstream_error");
    expect(body.error.message).toContain("500");
  });

  it("retorna 401 quando não há credentials", async () => {
    const app = new Hono();
    app.use("*", ensureToken({ loader: async () => null }));
    app.route("/v1/chat/completions", chatCompletionsRoutes({ async createResponse() { return new Response(); } }));

    const response = await app.request("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "gpt-5.1-codex", messages: [{ role: "user", content: "x" }] }),
    });

    expect(response.status).toBe(401);
  });

  it("converte stream response emitindo chunks no formato OpenAI", async () => {
    const encoder = new TextEncoder();
    const upstreamStream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"Hi"}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_1","object":"response","model":"gpt-5.1-codex","output":[],"usage":{"input_tokens":10,"output_tokens":5}}}\n\n',
          ),
        );
        controller.close();
      },
    });

    const { app } = buildApp({ status: 200, body: upstreamStream });

    const response = await app.request("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "Oi" }],
        stream: true,
      }),
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("text/event-stream");

    const text = await response.text();
    expect(text).toContain("chat.completion.chunk");
    expect(text).toContain('"content":"Hi"');
    expect(text).toContain("[DONE]");
  });
});
