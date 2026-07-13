interface JwtClaims {
  chatgpt_account_id?: string;
  organizations?: { id: string }[];
  "https://api.openai.com/auth"?: { chatgpt_account_id?: string };
  [key: string]: unknown;
}

/**
 * Decodes (without verifying) the payload of a JWT and returns its claims.
 * Returns `undefined` when the token is malformed or cannot be parsed.
 */
export function parseJwtClaims(token: string): JwtClaims | undefined {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return undefined;

    const payload = decodeBase64Url(parts[1]!);
    return JSON.parse(payload) as JwtClaims;
  } catch {
    return undefined;
  }
}

/**
 * Extracts the ChatGPT account id from a token response `id_token`, checking
 * the known claim locations used by the Codex OAuth flow.
 */
export function extractAccountId(idToken: string): string | undefined {
  const claims = parseJwtClaims(idToken);
  if (!claims) return undefined;

  return (
    claims.chatgpt_account_id ??
    claims["https://api.openai.com/auth"]?.chatgpt_account_id ??
    claims.organizations?.[0]?.id
  );
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}
