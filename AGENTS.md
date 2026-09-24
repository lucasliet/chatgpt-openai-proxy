# AGENTS.md

## Comandos canônicos

- Gerenciador de pacotes é **uv**; não usar `pip` direto nem trocar para outro runtime sem migração explícita.
- Instalar dependências: `uv sync` (inclui grupo dev; lock em `uv.lock` — manter atualizado com `uv lock`).
- Servidor local: `uv run fastapi dev` (reload). Produção: `uv run uvicorn app.main:app --host 0.0.0.0 --port 3000`.
- Verificação completa local/CI: `uv run pytest`.
- CI usa `uv sync --frozen` -> `uv run pytest` em `.github/workflows/ci.yml`.
- Teste focado: `uv run pytest tests/test_api.py::TestAdmin`.

## FastAPI Cloud

- Deploy alvo: https://fastapicloud.com/docs/ — o entrypoint está em `[tool.fastapi] entrypoint = "app.main:app"` no `pyproject.toml` (auto-detecção também acha `app/main.py`).
- `fastapi[standard]` deve permanecer em dependencies (CLI de deploy da plataforma).
- Python pinado em `.python-version` (3.12) e `requires-python` no pyproject.
- Config 100% por env vars (pydantic-settings); nada de segredos em arquivo versionado.
- `.fastapicloudignore` exclui `tests/`, `data/` etc. do upload; `.dockerignore` é só para o build Docker/GHCR.
- A plataforma faz autoscaling multi-instância com deploys zero-downtime: nada de estado em disco/memória compartilhado. Banco default local é SQLite; em produção `DATABASE_URL` aponta para Postgres (Neon/Supabase). `init_db()` usa `create_all` (idempotente) — não quebrar isso.
- Se `ADMIN_API_KEY` não estiver definida, uma chave é gerada por instância no boot (impressa nos logs). Em produção multi-instância a env é obrigatória para que todas as instâncias compartilhem a mesma chave.

## Entry point e roteamento

- `app/main.py` cria o app (`create_app()`) e expõe `app = create_app()` no módulo (importado pelo uvicorn/FastAPI Cloud). Não mover o objeto `app` de módulo.
- Rotas públicas: `GET /health`, `/login`, `/v1/models` e as rotas de proxy são protegidas por API key via dependency (`app/deps.py::require_api_key`), não por middleware.
- Erros HTTP com `detail={"error": {...}}` são promovidos ao topo do body pelo exception handler em `main.py` (formato OpenAI/Anthropic); manter esse contrato.

## Multi-usuário e API keys

- Chaves no formato `sk-<urlsafe>`; só o hash SHA-256 com salt (`app/security.py::_KEY_SALT`) é persistido. A chave completa é exibida uma única vez na criação.
- Toda rota de proxy exige `Authorization: Bearer sk-...`; keys revogadas (`revoked_at`) são rejeitadas com 401.
- Administração via `/admin/*` com header `X-Admin-Key`.

## OAuth, credenciais e engines

- Redirect OAuth real é `http://localhost:1455/auth/callback`; a porta é configurável via `OAUTH_CALLBACK_PORT` mas mudá-la provavelmente quebra o fluxo (whitelisting Codex).
- Env vars de credenciais (`CHATGPT_ACCESS_TOKEN`, `CHATGPT_REFRESH_TOKEN`, `CHATGPT_ACCOUNT_ID`, `CHATGPT_EXPIRES_AT`) têm precedência sobre o banco e só valem quando todas existem e `CHATGPT_EXPIRES_AT` é numérico (ms epoch). Env é read-only: refresh nunca persiste.
- Refresh pró-ativo com buffer de 5 min (`REFRESH_BUFFER_MS`), serializado por `asyncio.Lock` em `app/credentials.py`.
- Engine upstream em `app/codex.py`: `LiteLLMEngine` (default, `litellm.aresponses`, provider `openai/` + `api_base` do Codex + header `ChatGPT-Account-Id`) e `HttpxEngine` (`UPSTREAM_ENGINE=httpx`). As duas implementam a mesma interface (`responses` / `responses_stream`); ao alterar comportamento upstream, manter as duas consistentes.

## Conversores e compatibilidade de API

- `chat_to_responses` sempre envia `store: false`.
- Preserve o fallback `"You are a helpful assistant."` quando não houver system/developer; o backend Codex rejeita `instructions` vazio.
- Mensagens system/developer viram `instructions` concatenadas com `\n\n`; mensagens `tool` viram `function_call_output`.
- `tools[].function` é achatado para `tools[].{name, description, parameters}`.
- `max_tokens` vira `max_output_tokens`; `max_completion_tokens` sobrescreve `max_tokens`.
- Streams de chat terminam com `data: [DONE]\n\n`; streams da Anthropic usam linha `event:` + `data:` (`message_start`/`content_block_*`/`message_delta`/`message_stop`).
- Endpoints `/v1/responses` (passthrough), `/v1/chat/completions` e `/v1/messages`. Clientes Anthropic enviam `claude-*`; modelo fora da allowlist cai no `DEFAULT_MODEL` e o modelo solicitado é ecoado na resposta.

## Testes

- Testes usam `pytest` + `pytest-asyncio` (modo auto) + `respx` para mockar o upstream Codex (`tests/conftest.py` força `UPSTREAM_ENGINE=httpx` para determinismo).
- Fixtures constroem um app fresco por teste com SQLite em tmp path e env isolada (cuidado com o `lru_cache` de `get_settings` — usar `cache_clear()` + `database.reset_engine()`).
- Ao adicionar env vars novas em `Settings`, refletir em `.env.example`, README e `tests/conftest.py::_setup_env` quando aplicável.
