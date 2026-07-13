import { chmod, mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { credentialsFilePath } from "../config";
import type { Credentials, CredentialsSource } from "../types/credentials";

interface StoredCredentials {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  account_id: string;
}

/**
 * Loads the stored credentials. Environment variables take precedence over
 * the on-disk file, which makes headless/Docker deployments possible without
 * the OAuth flow.
 */
export async function loadCredentials(): Promise<{ credentials: Credentials; source: CredentialsSource } | null> {
  const fromEnv = loadFromEnv();
  if (fromEnv) return { credentials: fromEnv, source: "env" };

  const fromFile = await loadFromFile();
  if (fromFile) return { credentials: fromFile, source: "file" };

  return null;
}

/**
 * Persists credentials to the on-disk file with restrictive permissions
 * (`0600` for the file, `0700` for its parent directory). Writes are atomic
 * via a temporary file + rename. Environment-provided credentials are never
 * written back.
 */
export async function saveCredentials(credentials: Credentials): Promise<void> {
  const path = credentialsFilePath();
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  await chmod(dirname(path), 0o700);

  const payload: StoredCredentials = {
    access_token: credentials.accessToken,
    refresh_token: credentials.refreshToken,
    expires_at: credentials.expiresAt,
    account_id: credentials.accountId,
  };

  await atomicWriteJson(path, payload);
  await chmod(path, 0o600);
}

/**
 * Removes the on-disk credentials file if it exists.
 */
export async function deleteCredentials(): Promise<void> {
  await rm(credentialsFilePath(), { force: true });
}

function loadFromEnv(): Credentials | null {
  const accessToken = process.env.CHATGPT_ACCESS_TOKEN;
  const refreshToken = process.env.CHATGPT_REFRESH_TOKEN;
  const accountId = process.env.CHATGPT_ACCOUNT_ID;
  const expiresAtRaw = process.env.CHATGPT_EXPIRES_AT;

  if (!accessToken || !refreshToken || !accountId) return null;

  const expiresAt = expiresAtRaw ? Number(expiresAtRaw) : NaN;
  if (!Number.isFinite(expiresAt)) return null;

  return { accessToken, refreshToken, accountId, expiresAt };
}

async function loadFromFile(): Promise<Credentials | null> {
  try {
    const raw = await readFile(credentialsFilePath(), "utf8");
    const parsed = JSON.parse(raw) as StoredCredentials;
    return {
      accessToken: parsed.access_token,
      refreshToken: parsed.refresh_token,
      accountId: parsed.account_id,
      expiresAt: parsed.expires_at,
    };
  } catch {
    return null;
  }
}

async function atomicWriteJson(path: string, payload: unknown): Promise<void> {
  const tmp = `${path}.tmp`;
  await writeFile(tmp, JSON.stringify(payload, null, 2), { mode: 0o600, encoding: "utf8" });
  await rename(tmp, path);
}

export async function readFileMode(path: string): Promise<number | null> {
  try {
    const info = await stat(path);
    return info.mode & 0o777;
  } catch {
    return null;
  }
}
