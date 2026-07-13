import { createHash } from "node:crypto";

const PKCE_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

/**
 * Builds a high-entropy PKCE code verifier composed of 64 random characters
 * drawn from the unreserved URI characters set ([RFC 7636]).
 */
export function generateCodeVerifier(): string {
  return randomString(64);
}

/**
 * Builds a random 32-character `state` value used to bind the authorization
 * request to the callback and mitigate CSRF attacks.
 */
export function generateState(): string {
  return randomString(32);
}

/**
 * Derives the S256 PKCE code challenge for the given verifier:
 * `base64url(SHA-256(verifier))` without padding.
 */
export function generateCodeChallenge(verifier: string): string {
  const digest = createHash("sha256").update(verifier).digest();
  return digest.toString("base64url");
}

function randomString(length: number): string {
  const values = new Uint8Array(length);
  crypto.getRandomValues(values);
  let out = "";
  for (let i = 0; i < length; i++) {
    out += PKCE_CHARSET.charAt(values[i]! % PKCE_CHARSET.length);
  }
  return out;
}
