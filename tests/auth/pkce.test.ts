import { describe, expect, it } from "bun:test";
import { generateCodeChallenge, generateCodeVerifier, generateState } from "../../src/auth/pkce";

const PKCE_CHARSET = /^[A-Za-z0-9-._~]+$/;

describe("PKCE", () => {
  describe("generateCodeVerifier", () => {
    it("gera um verifier com exatamente 64 caracteres", () => {
      const verifier = generateCodeVerifier();

      expect(verifier).toHaveLength(64);
    });

    it("usa apenas caracteres do conjunto unreserved do RFC 7636", () => {
      const verifier = generateCodeVerifier();

      expect(verifier).toMatch(PKCE_CHARSET);
    });

    it("gera valores distintos a cada chamada", () => {
      const a = generateCodeVerifier();
      const b = generateCodeVerifier();

      expect(a).not.toBe(b);
    });
  });

  describe("generateState", () => {
    it("gera um state com exatamente 32 caracteres", () => {
      expect(generateState()).toHaveLength(32);
    });

    it("gera valores distintos a cada chamada", () => {
      expect(generateState()).not.toBe(generateState());
    });
  });

  describe("generateCodeChallenge", () => {
    it("é determinístico para o mesmo verifier", () => {
      const verifier = "test-verifier-123";

      expect(generateCodeChallenge(verifier)).toBe(generateCodeChallenge(verifier));
    });

    it("produz base64url sem padding (=)", () => {
      const challenge = generateCodeChallenge("another-verifier");

      expect(challenge).not.toContain("=");
      expect(challenge).not.toContain("+");
      expect(challenge).not.toContain("/");
    });

    it("produz o challenge esperado para um verifier conhecido", () => {
      const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
      const expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM";

      expect(generateCodeChallenge(verifier)).toBe(expected);
    });
  });
});
