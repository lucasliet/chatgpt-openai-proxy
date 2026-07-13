import { Hono } from "hono";
import type { Context } from "hono";
import { stream } from "hono/streaming";
import type { CodexClient } from "../../codex/client";
import { convertChatToResponses } from "../../converters/chat-to-responses";
import { convertResponsesToChat } from "../../converters/responses-to-chat";
import { convertResponsesStreamToChat } from "../../converters/stream-converter";
import type { ChatCompletionRequest } from "../../types/chat-completions";
import type { ResponsesResponse } from "../../types/responses";

/**
 * Mounts the `POST /v1/chat/completions` route. Converts the incoming Chat
 * Completions request to the Responses API format, forwards it to the Codex
 * backend, and converts the response back (streamed or non-streamed).
 */
export function chatCompletionsRoutes(client: CodexClient): Hono {
  const app = new Hono();

  app.post("/", async (c) => {
    const credentials = c.get("credentials");
    const request = (await c.req.json()) as ChatCompletionRequest;
    const payload = convertChatToResponses(request);

    const upstream = await client.createResponse(credentials, payload);

    if (!upstream.ok) {
      return relayError(upstream);
    }

    if (request.stream) {
      return streamChat(c, upstream, request.model);
    }

    const response = (await upstream.json()) as ResponsesResponse;
    return c.json(convertResponsesToChat(response));
  });

  return app;
}

async function streamChat(c: Context, upstream: Response, model: string) {
  c.header("Content-Type", "text/event-stream");
  c.header("Cache-Control", "no-cache");
  c.header("Connection", "keep-alive");

  const converted = convertResponsesStreamToChat(upstream.body!, model);
  return stream(c, async (stream) => {
    await stream.pipe(converted);
  });
}

async function relayError(upstream: Response): Promise<Response> {
  const text = await upstream.text();
  return new Response(
    JSON.stringify({
      error: {
        message: `Codex backend error (${upstream.status}): ${text}`,
        type: "upstream_error",
      },
    }),
    {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    },
  );
}
