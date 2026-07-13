import { describe, expect, it } from "bun:test";
import { Hono } from "hono";
import { modelsRoutes } from "../../../src/server/routes/models";

function buildApp(): Hono {
  const app = new Hono();
  app.route("/v1/models", modelsRoutes());
  return app;
}

describe("GET /v1/models", () => {
  it("retorna a lista no formato OpenAI", async () => {
    const response = await buildApp().request("/v1/models");

    expect(response.status).toBe(200);
    const body = (await response.json()) as { object: string; data: { id: string; object: string }[] };
    expect(body.object).toBe("list");
    expect(body.data.length).toBeGreaterThan(0);
    for (const model of body.data) {
      expect(model.object).toBe("model");
    }
  });

  it("inclui o modelo gpt-5.1-codex na lista", async () => {
    const response = await buildApp().request("/v1/models");
    const body = (await response.json()) as { data: { id: string }[] };

    expect(body.data.map((m) => m.id)).toContain("gpt-5.1-codex");
  });
});
