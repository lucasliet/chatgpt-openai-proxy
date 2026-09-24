# AGENTS.md

## Comandos canônicos

- Gerenciador de pacotes é **uv**; não usar `pip` direto nem trocar para outro runtime sem migração explícita.
- Instalar dependências: `uv sync` (inclui grupo dev; lock em `uv.lock` — manter atualizado com `uv lock`).
- Servidor local: `uv run fastapi dev` (reload). Produção: `uv run uvicorn app.main:app --host 0.0.0.0 --port 3000`.
- Verificação completa local/CI: `uv run pytest`.
- CI usa `uv sync --frozen` -> `uv run pytest` em `.github/workflows/ci.yml`.
- Teste focado: `uv run pytest tests/test_api.py::TestLoginFlow`.

## Modelo de autenticação (não quebrar)

- **OAuth é por usuário**: cada usuário autentica a própria conta ChatGPT via `/login`; os tokens ficam na linha de `proxy_user` e a API key gerada no login é a credencial de acesso ao proxy. Não existe credencial global compartilhada nem env vars `CHATGPT_*`.
- Re-login na mesma conta (identificada pelo `account_id` do id_token) faz upsert dos tokens, **revoga as keys antigas** e exibe uma nova. Re-login nunca duplica usuário.
- As rotas de proxy resolvem a cadeia: Bearer key → `ApiKey` (hash SHA-256 com salt) → `User` → credencial OAuth daquele usuário (com refresh pró-ativo de 5 min, lock por usuário).
- Clientes Anthropic enviam `claude-*`; modelo fora da allowlist cai no `DEFAULT_MODEL` e o modelo solicitado é ecoado na resposta.

## FastAPI Cloud

- Deploy alvo: https://fastapicloud.com/docs/ — entrypoint em `[tool.fastapi] entrypoint = "app.main:app"` no `pyproject.toml`.
- `fastapi[standard]` deve permanecer em dependencies (CLI de deploy da plataforma).
- Python pinado em `.python-version` (3.12) e `requires-python` no pyproject.
- Config 100% por env vars (pydantic-settings); nada de segredos em arquivo versionado.
- A plataforma faz autoscaling multi-instância com deploys zero-downtime: nada de estado em disco/memória compartilhado. Em produção `DATABASE_URL` vem da integração Neon. `init_db()` usa `create_all` + migração de colunas idempotente (`_USER_COLUMN_MIGRATIONS`) — não quebrar a idempotência.
- Se `ADMIN_API_KEY` não estiver definida, uma chave é gerada por instância no boot (impressa nos logs). Em produção multi-instância a env é obrigatória.

## Storage local (sem DATABASE_URL)

- Sem `DATABASE_URL`, o estado vai para `sqlite:///{CHATGPT_PROXY_HOME}/proxy.db` (default `~/.config/chatgpt-proxy`, mesma função do `credentials.json` do projeto anterior). Diretório `0700`, arquivo `0600` — manter.
- Docker/Compose monta o diretório como volume; não reintroduzir paths absolutos fora do proxy home.

## OAuth e conversores

- Redirect OAuth real é `http://localhost:1455/auth/callback`; a porta é configurável via `OAUTH_CALLBACK_PORT` mas mudá-la provavelmente quebra o fluxo (whitelisting Codex).
- `chat_to_responses` sempre envia `store: false`; fallback `"You are a helpful assistant."` quando não há system/developer (backend rejeita `instructions` vazio).
- system/developer → `instructions` com `\n\n`; `tool` → `function_call_output`; `tools[].function` achatado; `max_completion_tokens` sobrescreve `max_tokens`.
- Streams de chat terminam com `data: [DONE]\n\n`; streams Anthropic usam linha `event:` (`message_start`/`content_block_*`/`message_delta`/`message_stop`).
- Engine upstream em `app/codex.py`: `LiteLLMEngine` (default) e `HttpxEngine` (`UPSTREAM_ENGINE=httpx`), mesma interface (`responses` / `responses_stream`).

## Testes

- Testes usam `pytest` + `pytest-asyncio` (modo auto) + `respx` para mockar o upstream Codex (`tests/conftest.py` força `UPSTREAM_ENGINE=httpx`).
- Fixtures constroem um app fresco por teste com SQLite em tmp path e env isolada (cuidado com o `lru_cache` de `get_settings` — usar `cache_clear()` + `database.reset_engine()`).
- `tests/conftest.py` tem `create_user_with_credentials`/`create_api_key` para simular contas OAuth; fixtures de env globais de credencial foram removidas de propósito.
- Ao adicionar env vars novas em `Settings`, refletir em `.env.example`, README e `tests/conftest.py::_setup_env` quando aplicável.
