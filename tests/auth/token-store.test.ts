import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "bun:test";
import {
  deleteCredentials,
  loadCredentials,
  readFileMode,
  saveCredentials,
} from "../../src/auth/token-store";
import type { Credentials } from "../../src/types/credentials";

const ENV_KEYS = [
  "CHATGPT_ACCESS_TOKEN",
  "CHATGPT_REFRESH_TOKEN",
  "CHATGPT_ACCOUNT_ID",
  "CHATGPT_EXPIRES_AT",
] as const;

const savedEnv: Record<string, string | undefined> = {};
let sandbox: string;

beforeAll(() => {
  for (const key of ENV_KEYS) savedEnv[key] = process.env[key];
});

beforeEach(async () => {
  for (const key of ENV_KEYS) delete process.env[key];
  sandbox = await mkdtemp(join(tmpdir(), "cgp-test-"));
  process.env.CHATGPT_PROXY_HOME = sandbox;
});

afterAll(() => {
  for (const key of ENV_KEYS) {
    if (savedEnv[key] === undefined) delete process.env[key];
    else process.env[key] = savedEnv[key];
  }
});

const sampleCredentials: Credentials = {
  accessToken: "access-123",
  refreshToken: "refresh-456",
  accountId: "org-account-789",
  expiresAt: 2_000_000_000_000,
};

describe("token-store", () => {
  describe("loadCredentials", () => {
    it("retorna null quando não há env nem arquivo", async () => {
      expect(await loadCredentials()).toBeNull();
    });

    it("carrega credentials a partir do arquivo salvo", async () => {
      await saveCredentials(sampleCredentials);

      const result = await loadCredentials();

      expect(result?.source).toBe("file");
      expect(result?.credentials).toEqual(sampleCredentials);
    });

    it("env vars têm precedência sobre o arquivo", async () => {
      await saveCredentials(sampleCredentials);
      const envCredentials: Credentials = {
        accessToken: "env-access",
        refreshToken: "env-refresh",
        accountId: "env-account",
        expiresAt: 1_500_000_000_000,
      };
      setEnvCredentials(envCredentials);

      const result = await loadCredentials();

      expect(result?.source).toBe("env");
      expect(result?.credentials).toEqual(envCredentials);
    });

    it("carrega do arquivo quando env está parcialmente definido", async () => {
      await saveCredentials(sampleCredentials);
      process.env.CHATGPT_ACCESS_TOKEN = "only-access";
      process.env.CHATGPT_REFRESH_TOKEN = "only-refresh";

      const result = await loadCredentials();

      expect(result?.source).toBe("file");
    });

    it("retorna null quando env está incompleto e não há arquivo", async () => {
      process.env.CHATGPT_ACCESS_TOKEN = "orphan-access";

      expect(await loadCredentials()).toBeNull();
    });

    it("retorna null quando expires_at do env não é numérico", async () => {
      process.env.CHATGPT_ACCESS_TOKEN = "a";
      process.env.CHATGPT_REFRESH_TOKEN = "r";
      process.env.CHATGPT_ACCOUNT_ID = "acc";
      process.env.CHATGPT_EXPIRES_AT = "not-a-number";

      expect(await loadCredentials()).toBeNull();
    });
  });

  describe("saveCredentials", () => {
    it("escreve o arquivo com permissão 0600", async () => {
      await saveCredentials(sampleCredentials);

      const mode = await readFileMode(`${sandbox}/credentials.json`);
      expect(mode).toBe(0o600);
    });

    it("cria o diretório pai com permissão 0700", async () => {
      await saveCredentials(sampleCredentials);

      const mode = await readFileMode(sandbox);
      expect(mode).toBe(0o700);
    });

    it("sobrescreve credentials previamente salvas sem corromper", async () => {
      await saveCredentials(sampleCredentials);
      const updated: Credentials = { ...sampleCredentials, accessToken: "new-access" };
      await saveCredentials(updated);

      const raw = await readFile(`${sandbox}/credentials.json`, "utf8");
      const parsed = JSON.parse(raw);

      expect(parsed.access_token).toBe("new-access");
    });

    it("não deixa arquivo temporário para trás", async () => {
      await saveCredentials(sampleCredentials);

      await expect(readFile(`${sandbox}/credentials.json.tmp`, "utf8")).rejects.toBeDefined();
    });
  });

  describe("deleteCredentials", () => {
    it("remove o arquivo de credentials existente", async () => {
      await saveCredentials(sampleCredentials);
      await deleteCredentials();

      expect(await loadCredentials()).toBeNull();
    });

    it("não lança erro quando o arquivo não existe", async () => {
      await expect(deleteCredentials()).resolves.toBeUndefined();
    });
  });
});

function setEnvCredentials(credentials: Credentials): void {
  process.env.CHATGPT_ACCESS_TOKEN = credentials.accessToken;
  process.env.CHATGPT_REFRESH_TOKEN = credentials.refreshToken;
  process.env.CHATGPT_ACCOUNT_ID = credentials.accountId;
  process.env.CHATGPT_EXPIRES_AT = String(credentials.expiresAt);
}
