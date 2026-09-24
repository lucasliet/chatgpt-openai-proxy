"""Helpers compartilhados dos routers de proxy."""

from fastapi.responses import JSONResponse

from ..codex import UpstreamError


def upstream_error_response(error: UpstreamError) -> JSONResponse:
    """Resposta de erro padronizada para falhas do backend Codex."""
    return JSONResponse(
        status_code=error.status if 400 <= error.status < 600 else 502,
        content={
            "error": {
                "message": str(error),
                "type": "upstream_error",
            }
        },
    )
