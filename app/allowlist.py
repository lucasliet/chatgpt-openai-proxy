"""Allowlist de modelos do ChatGPT Plan (port de ``codex/models.ts``)."""

ALLOWED_MODELS = [
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-5.2-codex",
    "gpt-5.3-codex",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.5",
    "codex-mini-latest",
]

_MODEL_CREATED_AT = 1_700_000_000


def list_allowed_models() -> dict:
    """Allowlist formatada como lista de modelos OpenAI-compatible."""
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": _MODEL_CREATED_AT,
                "owned_by": "chatgpt-plan",
            }
            for model_id in ALLOWED_MODELS
        ],
    }


def is_allowed_model(model: str) -> bool:
    """Indica se o modelo pertence à allowlist do ChatGPT Plan."""
    return model in ALLOWED_MODELS
