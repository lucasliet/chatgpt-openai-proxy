import { config, oauthRedirectUri } from "../config";
import type { Credentials, TokenResponse } from "../types/credentials";
import { generateCodeChallenge } from "./pkce";
import { extractAccountId } from "./jwt";

export interface OAuthParams {
  codeVerifier: string;
  state: string;
}

/**
 * Builds the PKCE-protected authorization URL for the Codex OAuth flow,
 * embedding the verifier challenge, state, and Codex-specific parameters.
 */
export function buildAuthUrl(params: OAuthParams): string {
  const codeChallenge = generateCodeChallenge(params.codeVerifier);
  const url = new URL(config.oauth.authUrl);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", config.oauth.clientId);
  url.searchParams.set("redirect_uri", oauthRedirectUri());
  url.searchParams.set("scope", config.oauth.scope);
  url.searchParams.set("state", params.state);
  url.searchParams.set("code_challenge", codeChallenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("codex_cli_simplified_flow", "true");
  url.searchParams.set("originator", "codex_cli_rs");
  return url.toString();
}

/**
 * Exchanges an authorization code for OAuth tokens using the PKCE verifier.
 * Throws on non-2xx responses with the status code and response body.
 */
export async function exchangeCodeForTokens(code: string, params: OAuthParams): Promise<TokenResponse> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: config.oauth.clientId,
    code,
    redirect_uri: oauthRedirectUri(),
    code_verifier: params.codeVerifier,
  });

  return postTokenRequest(body);
}

/**
 * Refreshes the access token using a long-lived refresh token. The returned
 * `refresh_token` (if present) must replace the stored one.
 */
export async function refreshAccessToken(refreshToken: string): Promise<TokenResponse> {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: config.oauth.clientId,
    refresh_token: refreshToken,
  });

  return postTokenRequest(body);
}

/**
 * Converts a token response into the internal `Credentials` shape, extracting
 * the account id from the `id_token` JWT when present.
 */
export function toCredentials(token: TokenResponse, fallbackAccountId?: string): Credentials {
  const accountId = token.id_token ? extractAccountId(token.id_token) : undefined;
  return {
    accessToken: token.access_token,
    refreshToken: token.refresh_token ?? "",
    expiresAt: Date.now() + token.expires_in * 1000,
    accountId: accountId ?? fallbackAccountId ?? "",
  };
}

async function postTokenRequest(body: URLSearchParams): Promise<TokenResponse> {
  const response = await fetch(config.oauth.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Token request failed (${response.status}): ${errorBody}`);
  }

  return (await response.json()) as TokenResponse;
}
