import { config } from "../config";
import type { Credentials } from "../types/credentials";
import type { ResponsesRequest } from "../types/responses";

export interface CodexClient {
  createResponse(credentials: Credentials, body: ResponsesRequest): Promise<Response>;
}

interface CodexClientDeps {
  fetch?: typeof fetch;
}

/**
 * Builds a client that forwards Responses API requests to the Codex backend at
 * `chatgpt.com/backend-api/codex`, injecting the OAuth bearer token and the
 * ChatGPT account id header required by the subscription.
 */
export function createCodexClient(deps: CodexClientDeps = {}): CodexClient {
  const doFetch = deps.fetch ?? fetch;
  return {
    async createResponse(credentials, body) {
      return doFetch(`${config.codexBaseUrl}/responses`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${credentials.accessToken}`,
          "ChatGPT-Account-Id": credentials.accountId,
        },
        body: JSON.stringify(body),
      });
    },
  };
}
