import { Hono } from "hono";
import { logger } from "hono/logger";
import { createCodexClient } from "../codex/client";
import { ensureToken } from "./middleware/ensure-token";
import { chatCompletionsRoutes } from "./routes/chat-completions";
import { modelsRoutes } from "./routes/models";
import { responsesRoutes } from "./routes/responses";

/**
 * Builds the Hono application wiring middlewares and mounting the OpenAI-
 * compatible routes (chat completions, responses passthrough, models).
 */
export function buildApp(): Hono {
  const app = new Hono();
  app.use("*", logger());

  const codexClient = createCodexClient();

  app.get("/health", (c) => c.json({ status: "ok" }));

  app.route("/v1/models", modelsRoutes());

  app.use("/v1/responses", ensureToken());
  app.use("/v1/responses/*", ensureToken());
  app.route("/v1/responses", responsesRoutes(codexClient));

  app.use("/v1/chat/completions", ensureToken());
  app.use("/v1/chat/completions/*", ensureToken());
  app.route("/v1/chat/completions", chatCompletionsRoutes(codexClient));

  return app;
}
