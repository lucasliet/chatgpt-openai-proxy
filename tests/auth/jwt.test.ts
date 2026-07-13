import { describe, expect, it } from "bun:test";
import { extractAccountId, parseJwtClaims } from "../../src/auth/jwt";

function buildJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "none", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload)).replace(/=/g, "");
  return `${header}.${body}.signature`;
}

describe("JWT", () => {
  describe("parseJwtClaims", () => {
    it("decodifica o payload de um JWT válido", () => {
      const token = buildJwt({ sub: "user-123", email: "test@example.com" });

      const claims = parseJwtClaims(token);

      expect(claims?.sub).toBe("user-123");
      expect(claims?.email).toBe("test@example.com");
    });

    it("aceita payload codificado em base64url (com - e _)", () => {
      const payload = { name: "Lucas Oliveira" };
      const body = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
      const token = `header.${body}.sig`;

      expect(parseJwtClaims(token)?.name).toBe("Lucas Oliveira");
    });

    it("retorna undefined para token sem as 3 partes", () => {
      expect(parseJwtClaims("not-a-jwt")).toBeUndefined();
    });

    it("retorna undefined para payload não-JSON", () => {
      const token = `header.${btoa("<<<not json>>>")}.sig`;

      expect(parseJwtClaims(token)).toBeUndefined();
    });
  });

  describe("extractAccountId", () => {
    it("encontra o account id em chatgpt_account_id", () => {
      const token = buildJwt({ chatgpt_account_id: "org-abc-123" });

      expect(extractAccountId(token)).toBe("org-abc-123");
    });

    it("encontra o account id no namespace da OpenAI", () => {
      const token = buildJwt({ "https://api.openai.com/auth": { chatgpt_account_id: "org-ns-456" } });

      expect(extractAccountId(token)).toBe("org-ns-456");
    });

    it("faz fallback para organizations[0].id", () => {
      const token = buildJwt({ organizations: [{ id: "org-fallback-789" }] });

      expect(extractAccountId(token)).toBe("org-fallback-789");
    });

    it("prioriza chatgpt_account_id sobre organizations", () => {
      const token = buildJwt({
        chatgpt_account_id: "org-priority",
        organizations: [{ id: "org-secondary" }],
      });

      expect(extractAccountId(token)).toBe("org-priority");
    });

    it("retorna undefined quando nenhuma claim de conta existe", () => {
      const token = buildJwt({ sub: "user-no-account" });

      expect(extractAccountId(token)).toBeUndefined();
    });

    it("retorna undefined para token malformado sem lançar erro", () => {
      expect(extractAccountId("garbage")).toBeUndefined();
    });
  });
});
