# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime
WORKDIR /app

# uv gerencia as dependências (mesma lock do desenvolvimento).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

# SQLite + keyfile de criptografia no volume; em produção prefira Postgres via
# DATABASE_URL (aí TOKEN_ENCRYPTION_KEY passa a ser obrigatória).
ENV CHATGPT_PROXY_HOME=/data
ENV PORT=3000
ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
USER appuser

VOLUME ["/data"]
EXPOSE 3000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
