import { Hono } from "hono";
import { listAllowedModels } from "../../codex/models";

/**
 * Mounts the `GET /v1/models` route returning the ChatGPT Plan allowlist in
 * the OpenAI-compatible list format.
 */
export function modelsRoutes(): Hono {
  const app = new Hono();

  app.get("/", (c) => c.json(listAllowedModels()));

  return app;
}
