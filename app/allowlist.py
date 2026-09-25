"""Allowlist de modelos do ChatGPT Plan — fallback do GET /v1/models.

O proxy tenta listar dinamicamente de ``{codex_base_url}/models``; esta
lista estática só é usada se essa chamada falhar. Atualizada em
2026-09-25 com os modelos suportados pelo backend do plano
(gpt-5.* anteriores foram removidos: "model is not supported").
"""

ALLOWED_MODELS = [
    "gpt-6-luna",
    "gpt-6-terra",
    "gpt-6-sol",
    "gpt-6-astra",
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
