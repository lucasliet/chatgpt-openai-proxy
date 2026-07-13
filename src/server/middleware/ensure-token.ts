import type { Context, MiddlewareHandler } from "hono";
import type { Credentials } from "../../types/credentials";
import { refreshAccessToken } from "../../auth/oauth-client";
import { loadCredentials, saveCredentials } from "../../auth/token-store";

const REFRESH_BUFFER_MS = 5 * 60 * 1000;

declare module "hono" {
  interface ContextVariableMap {
    credentials: Credentials;
  }
}

export interface EnsureTokenDeps {
  loader?: typeof loadCredentials;
  refresher?: typeof refreshAccessToken;
  persister?: typeof saveCredentials;
}

/**
 * Middleware that guarantees a fresh OAuth credential is available on the
 * request context. Loads from env/file, proactively refreshes when the token
 * expires within 5 minutes, and rejects with 401 when no credentials exist.
 */
export function ensureToken(deps: EnsureTokenDeps = {}): MiddlewareHandler {
  const loader = deps.loader ?? loadCredentials;
  const refresher = deps.refresher ?? refreshAccessToken;
  const persister = deps.persister ?? saveCredentials;

  return async (c, next) => {
    const loaded = await loader();
    if (!loaded) {
      return unauthorized(c);
    }

    const credentials = await refreshIfNeeded(loaded.credentials, loaded.source, refresher, persister);
    c.set("credentials", credentials);
    await next();
  };
}

async function refreshIfNeeded(
  credentials: Credentials,
  source: "env" | "file",
  refresher: typeof refreshAccessToken,
  persister: typeof saveCredentials,
): Promise<Credentials> {
  if (credentials.expiresAt > Date.now() + REFRESH_BUFFER_MS) {
    return credentials;
  }

  if (!credentials.refreshToken) {
    return credentials;
  }

  try {
    const token = await refresher(credentials.refreshToken);
    const refreshed: Credentials = {
      accessToken: token.access_token,
      refreshToken: token.refresh_token ?? credentials.refreshToken,
      expiresAt: Date.now() + token.expires_in * 1000,
      accountId: credentials.accountId,
    };

    if (source === "file") {
      await persister(refreshed);
    }
    return refreshed;
  } catch {
    return credentials;
  }
}

function unauthorized(c: Context): Response {
  return c.json(
    {
      error: {
        message: "No ChatGPT credentials found. Open /login in your browser to authenticate, or set CHATGPT_ACCESS_TOKEN env vars.",
        type: "authentication_error",
        code: "no_credentials",
      },
    },
    401,
  );
}
