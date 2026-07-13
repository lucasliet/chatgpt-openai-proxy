import { describe, expect, it, mock } from "bun:test";
import { Hono } from "hono";
import { ensureToken } from "../../../src/server/middleware/ensure-token";
import type { Credentials } from "../../../src/types/credentials";

const freshCredentials: Credentials = {
  accessToken: "fresh-access",
  refreshToken: "fresh-refresh",
  accountId: "org-fresh",
  expiresAt: Date.now() + 3_600_000,
};

const expiringCredentials: Credentials = {
  accessToken: "expiring-access",
  refreshToken: "expiring-refresh",
  accountId: "org-expiring",
  expiresAt: Date.now() + 60_000,
};

function buildApp(
  loadResult: { credentials: Credentials; source: "env" | "file" } | null,
  options: {
    refreshResult?: () => Promise<{ access_token: string; refresh_token?: string; expires_in: number }>;
    persistMock?: ReturnType<typeof mock>;
  } = {},
) {
  const app = new Hono();
  const refreshMock = options.refreshResult ? mock(options.refreshResult) : mock(async () => ({ access_token: "ignored", expires_in: 3600 }));
  const persistMock = options.persistMock ?? mock(async () => {});

  app.use(
    "*",
    ensureToken({
      loader: async () => loadResult,
      refresher: refreshMock as unknown as typeof import("../../../src/auth/oauth-client").refreshAccessToken,
      persister: persistMock as unknown as typeof import("../../../src/auth/token-store").saveCredentials,
    }),
  );
  app.get("/probe", (c) => c.json({ accountId: c.get("credentials").accountId }));
  return { app, refreshMock, persistMock };
}

describe("ensureToken middleware", () => {
  it("anexa credentials frescas no contexto e segue", async () => {
    const { app, refreshMock } = buildApp({ credentials: freshCredentials, source: "file" });

    const response = await app.request("/probe");

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ accountId: "org-fresh" });
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("retorna 401 quando não há credentials", async () => {
    const { app } = buildApp(null);

    const response = await app.request("/probe");

    expect(response.status).toBe(401);
    const body = (await response.json()) as { error: { type: string; message: string } };
    expect(body.error.type).toBe("authentication_error");
    expect(body.error.message).toContain("login");
  });

  it("atualiza proativamente tokens que expiram em menos de 5 minutos", async () => {
    const { app, refreshMock, persistMock } = buildApp(
      { credentials: expiringCredentials, source: "file" },
      {
        refreshResult: async () => ({
          access_token: "new-access",
          refresh_token: "rotated-refresh",
          expires_in: 3600,
        }),
      },
    );

    const response = await app.request("/probe");

    expect(response.status).toBe(200);
    expect(refreshMock).toHaveBeenCalledTimes(1);
    const firstCallArgs = (refreshMock.mock.calls as unknown as string[][])[0]![0];
    expect(firstCallArgs).toBe("expiring-refresh");
    expect(await response.json()).toEqual({ accountId: "org-expiring" });
    expect(persistMock).toHaveBeenCalledTimes(1);
  });

  it("persiste o token renovado apenas quando a origem é file", async () => {
    const { persistMock } = buildApp(
      { credentials: expiringCredentials, source: "env" },
      {
        refreshResult: async () => ({
          access_token: "new-access",
          expires_in: 3600,
        }),
      },
    );

    await buildApp(
      { credentials: expiringCredentials, source: "env" },
      {
        refreshResult: async () => ({ access_token: "new-access", expires_in: 3600 }),
        persistMock,
      },
    ).app.request("/probe");

    expect(persistMock).not.toHaveBeenCalled();
  });

  it("mantém o token antigo quando o refresh falha", async () => {
    const { app, refreshMock } = buildApp(
      { credentials: expiringCredentials, source: "file" },
      {
        refreshResult: async () => {
          throw new Error("refresh failed");
        },
      },
    );

    const response = await app.request("/probe");

    expect(response.status).toBe(200);
    expect(refreshMock).toHaveBeenCalled();
    expect(await response.json()).toEqual({ accountId: "org-expiring" });
  });
});
