import { Hono } from "hono";
import { stream } from "hono/streaming";
import type { CodexClient } from "../../codex/client";
import type { ResponsesRequest } from "../../types/responses";

/**
 * Mounts the `POST /v1/responses` passthrough route. Forwards the request body
 * untouched to the Codex backend and relays the response (streamed or not).
 */
export function responsesRoutes(client: CodexClient): Hono {
  const app = new Hono();

  app.post("/", async (c) => {
    const credentials = c.get("credentials");
    const body = (await c.req.json()) as ResponsesRequest;

    const upstream = await client.createResponse(credentials, body);

    if (!upstream.ok) {
      return relayError(upstream);
    }

    if (body.stream) {
      c.header("Content-Type", "text/event-stream");
      c.header("Cache-Control", "no-cache");
      c.header("Connection", "keep-alive");
      return stream(c, async (stream) => {
        await stream.pipe(upstream.body!);
      });
    }

    return new Response(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  });

  return app;
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
