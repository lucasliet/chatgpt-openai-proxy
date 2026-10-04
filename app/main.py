"""App FastAPI — entrypoint detectado pelo FastAPI Cloud e por `uvicorn`.

Uso local:

    uv run fastapi dev          # modo desenvolvimento (com reload)
    uv run uvicorn app.main:app # modo produção

Deploy no FastAPI Cloud: ``fastapi deploy`` (o entrypoint ``app.main:app``
está configurado em ``[tool.fastapi]`` no pyproject.toml).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from .codex import build_engine
from .config import Settings, get_settings, resolved_database_url
from .database import init_db
from .pricing import maintain_telemetry
from .routers import (
    admin,
    anthropic,
    backoffice,
    chat,
    dashboard,
    home,
    login,
    logout,
    models,
    responses,
    subscription,
)
from .security import generate_api_key
from .subscription import SubscriptionService
from .telemetry import purge_expired

logger = logging.getLogger("chatgpt-proxy")

# O runner do FastAPI Cloud (uvicorn) não configura o root logger: sem isso,
# logs de aplicação (ex.: origem da listagem de /v1/models) nunca saem.
logging.basicConfig(level=logging.INFO)


def _bootstrap_admin_key(settings: Settings) -> None:
    """Garante uma chave de admin disponível.

    Com ``ADMIN_API_KEY`` definida, usa-a. Caso contrário, gera uma aleatória
    no boot e imprime nos logs (única exibição). Em deploy multi-instância
    (FastAPI Cloud) defina a env para que todas as instâncias compartilhem a
    mesma chave.
    """
    if settings.admin_api_key:
        return
    settings.admin_api_key = generate_api_key()
    logger.warning(
        "ADMIN_API_KEY não definida — chave de admin gerada para este boot: %s\n"
        "Defina a env ADMIN_API_KEY para uma chave fixa compartilhada entre instâncias.",
        settings.admin_api_key,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await asyncio.to_thread(purge_expired)
    _bootstrap_admin_key(app.state.settings)
    db_target = resolved_database_url(app.state.settings).split("@")[-1]  # oculta credenciais
    logger.info("Proxy pronto (engine=%s, db=%s)", app.state.engine.name, db_target)
    maintenance = asyncio.create_task(maintain_telemetry(app.state.settings.pricing_enabled))
    try:
        yield
    finally:
        maintenance.cancel()
        try:
            await maintenance
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="chatgpt-openai-proxy", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = build_engine(settings)
    app.state.subscription = SubscriptionService(settings)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.cookie_secret,
        same_site="lax",
        https_only=False,
        max_age=300,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Guards de páginas HTML sinalizam redirect via 3xx + Location.
        if 300 <= exc.status_code < 400 and exc.headers and "Location" in exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
        # Erros no formato {"error": ...} são promovidos ao topo do body,
        # mantendo compatibilidade com clientes OpenAI/Anthropic.
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content={"error": detail["error"]})
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(home.router, tags=["home"])
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(login.router, prefix="/login", tags=["login"])
    app.include_router(logout.router, prefix="/logout", tags=["logout"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])
    app.include_router(backoffice.router, tags=["backoffice"])
    app.include_router(backoffice.backoffice_router, tags=["backoffice"])
    app.include_router(models.router, prefix="/v1/models", tags=["models"])
    app.include_router(subscription.router, prefix="/v1/usage", tags=["usage"])
    app.include_router(responses.router, prefix="/v1/responses", tags=["responses"])
    app.include_router(chat.router, prefix="/v1/chat/completions", tags=["chat"])
    app.include_router(anthropic.router, prefix="/v1/messages", tags=["anthropic"])

    return app


app = create_app()
