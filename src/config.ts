import { homedir } from "node:os";
import { join } from "node:path";

const env = process.env;

function numberEnv(key: string, fallback: number): number {
  const raw = env[key];
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const config = {
  port: numberEnv("PORT", 3000),
  get oauthCallbackPort() {
    return numberEnv("OAUTH_CALLBACK_PORT", 1455);
  },
  get codexBaseUrl() {
    return env.CODEX_BASE_URL ?? "https://chatgpt.com/backend-api/codex";
  },
  get proxyHome() {
    return env.CHATGPT_PROXY_HOME ?? join(homedir(), ".config", "chatgpt-proxy");
  },
  get cookieSecret() {
    return env.COOKIE_SECRET ?? "chatgpt-proxy-dev-secret";
  },
  oauth: {
    clientId: "app_EMoamEEZ73f0CkXaXp7hrann",
    authUrl: "https://auth.openai.com/oauth/authorize",
    tokenUrl: "https://auth.openai.com/oauth/token",
    scope: "offline_access openid profile email",
  },
};

export function credentialsFilePath() {
  return join(config.proxyHome, "credentials.json");
}

export function oauthRedirectUri() {
  return `http://localhost:${config.oauthCallbackPort}/auth/callback`;
}
