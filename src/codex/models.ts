export const ALLOWED_MODELS = [
  "gpt-5.1-codex",
  "gpt-5.1-codex-max",
  "gpt-5.1-codex-mini",
  "gpt-5.2-codex",
  "gpt-5.3-codex",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.5",
  "codex-mini-latest",
] as const;

export type AllowedModel = (typeof ALLOWED_MODELS)[number];

const MODEL_CREATED_AT = 1_700_000_000;

export interface OpenAiModel {
  id: string;
  object: "model";
  created: number;
  owned_by: string;
}

/**
 * Returns the ChatGPT Plan allowlist formatted as an OpenAI-compatible model
 * list, suitable for the `GET /v1/models` endpoint.
 */
export function listAllowedModels(): { object: "list"; data: OpenAiModel[] } {
  return {
    object: "list",
    data: ALLOWED_MODELS.map((id) => ({
      id,
      object: "model",
      created: MODEL_CREATED_AT,
      owned_by: "chatgpt-plan",
    })),
  };
}

/**
 * Checks whether a model id is part of the ChatGPT Plan allowlist.
 */
export function isAllowedModel(model: string): boolean {
  return (ALLOWED_MODELS as readonly string[]).includes(model);
}
