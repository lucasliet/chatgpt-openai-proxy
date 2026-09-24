# chatgpt-openai-proxy

Proxy **OpenAI + Anthropic** compatível que roteia requests para o **ChatGPT Plan (Codex)** via OAuth, reescrito em **FastAPI** com suporte a **multi-usuário** e **API keys por usuário**, pronto para deploy no **[FastAPI Cloud](https://fastapicloud.com)**.

## Features

- **Três formatos de entrada** sobre a mesma assinatura do ChatGPT:
  - `POST /v1/responses` — Responses API (passthrough)
  - `POST /v1/chat/completions` — Chat Completions API (conversão bidirecional)
  - `POST /v1/messages` — Anthropic Messages API (conversão bidirecional, streaming com eventos oficiais)
- **Multi-usuário**: usuários com API keys próprias (`sk-...`), revogação e `last_used_at` — tudo administrado via `/admin/*`
- **Engine upstream intercambiável**: [LiteLLM](https://docs.litellm.ai/docs/response_api) (`litellm.aresponses`, default) ou HTTPX direto (`UPSTREAM_ENGINE=httpx`)
- **OAuth PKCE** com fluxo web em `/login` (modo "colar URL de callback" para headless/Docker) ou credenciais via env vars
- **Refresh automático** do access token (5 min de antecedência)
- **Streaming SSE** completo nos três formatos
- **Banco agnóstico**: SQLite local, Postgres (Neon/Supabase) em produção

## Quick start local

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e Python 3.12.

```bash
uv sync
uv run fastapi dev
```

Acesse `http://localhost:3000/login`, autorize com sua conta ChatGPT e cole a URL de callback. Pronto — o proxy já pode atender requests.

## Deploy no FastAPI Cloud

O projeto já segue as convenções da plataforma (entrypoint em `[tool.fastapi]` do `pyproject.toml`, `fastapi[standard]`, `.python-version`):

```bash
uvx fastapi login          # ou: fastapi login
fastapi cloud env set --secret ADMIN_API_KEY "sk-admin-segura"
fastapi cloud env set --secret COOKIE_SECRET "segredo-aleatorio"
fastapi cloud env set DATABASE_URL "postgresql://...neon..."   # Postgres gerenciado
fastapi deploy
```

Depois do deploy, autentique a assinatura abrindo `https://<seu-app>.fastapicloud.dev/login` (modo "colar URL de callback" — o redirect localhost não precisa ser alcançável).

> **Por que Postgres?** O FastAPI Cloud faz autoscaling com múltiplas instâncias e deploys zero-downtime; SQLite em disco não é compartilhado entre instâncias. Use a integração [Neon](https://fastapicloud.com/docs/integrations/neon-integration/) ou [Supabase](https://fastapicloud.com/docs/integrations/supabase-integration/). A criação de tabelas é idempotente (`CREATE TABLE IF NOT EXISTS`) e roda no boot de cada instância.

## Uso

### 1. Criar usuário e API key (admin)

```bash
curl -X POST localhost:3000/admin/users \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "alice"}'

curl -X POST localhost:3000/admin/users/1/keys \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"label": "notebook"}'
# → {"key": "sk-...", ...}  # exibida apenas desta vez
```

Endpoints admin: `GET /admin/users` · `DELETE /admin/users/{id}` · `GET /admin/users/{id}/keys` · `POST /admin/users/{id}/keys` · `POST /admin/keys/{id}/revoke` · `GET /admin/credentials` · `DELETE /admin/credentials`.

Se `ADMIN_API_KEY` não for definida, uma chave é gerada no boot e impressa nos logs (defina a env em produção multi-instância).

### 2. Chamar a API

```bash
export KEY="sk-..."

# Chat Completions
curl localhost:3000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-5.1-codex", "messages": [{"role": "user", "content": "oi"}]}'

# Responses API
curl localhost:3000/v1/responses \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-5.1-codex", "input": "oi", "store": false}'

# Anthropic Messages (clientes Claude funcionam apontando base_url aqui)
curl localhost:3000/v1/messages \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-4-5", "max_tokens": 1024, "messages": [{"role": "user", "content": "oi"}]}'
```

Streaming (`"stream": true`) funciona nos três endpoints.

Compatibilidade com clientes oficiais:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:3000/v1", api_key="sk-...")
client.chat.completions.create(model="gpt-5.1-codex", messages=[...])
```

```python
import anthropic
client = anthropic.Anthropic(base_url="http://localhost:3000", api_key="sk-...")
client.messages.create(model="claude-sonnet-4-5", max_tokens=1024, messages=[...])
# modelos claude-* caem no DEFAULT_MODEL (gpt-5.1-codex) upstream
```

### 3. Credenciais ChatGPT

Duas fontes, com precedência **env vars > banco**:

| Fonte | Como | Observação |
| --- | --- | --- |
| Env vars | `CHATGPT_ACCESS_TOKEN`, `CHATGPT_REFRESH_TOKEN`, `CHATGPT_ACCOUNT_ID`, `CHATGPT_EXPIRES_AT` | Read-only (refresh não persiste). Ideal para Docker/CI. Só valem quando **todas** existem e `CHATGPT_EXPIRES_AT` é numérico (ms epoch) |
| Banco | Fluxo web `/login` | Padrão para deploys; persiste refresh no Postgres/SQLite |

## Configuração

| Env var | Default | Descrição |
| --- | --- | --- |
| `PORT` | `3000` | Porta do servidor |
| `DATABASE_URL` | `sqlite:///./data/proxy.db` | SQLAlchemy URL (SQLite local; Postgres em produção) |
| `UPSTREAM_ENGINE` | `litellm` | `litellm` (default) ou `httpx` |
| `DEFAULT_MODEL` | `gpt-5.1-codex` | Modelo quando o pedido está fora da allowlist |
| `ADMIN_API_KEY` | — (gerada no boot) | Chave dos endpoints `/admin/*` |
| `COOKIE_SECRET` | dev | Segredo do cookie de sessão do `/login` |
| `CODEX_BASE_URL` | `https://chatgpt.com/backend-api/codex` | Backend do plano ChatGPT |

## Docker

```bash
docker compose up -d    # usa a imagem publicada no GHCR
```

Para publicar a imagem localmente (validação do Dockerfile): `docker build -t chatgpt-proxy .`

## Desenvolvimento

```bash
uv sync                 # instala deps (inclui grupo dev)
uv run pytest           # suíte completa (upstream mockado com respx)
uv run fastapi dev      # servidor com reload
```

Arquitetura:

```
app/
├── main.py            # app FastAPI, lifespan, exception handler
├── config.py          # settings via env (pydantic-settings)
├── database.py        # engine + init idempotente
├── models.py          # User, ApiKey, Setting (SQLModel)
├── security.py        # geração/hash de keys, auth admin
├── oauth.py           # PKCE, troca/refresh de token, JWT
├── credentials.py     # store de credenciais (env > banco) + refresh
├── codex.py           # engines LiteLLM/HTTPX
├── deps.py            # dependencies de auth
├── allowlist.py       # modelos do ChatGPT Plan
├── converters/        # chat↔responses, SSE, anthropic↔chat
└── routers/           # login, admin, models, responses, chat, anthropic
```

## Por que não LiteLLM nos conversores?

O LiteLLM é usado como **engine upstream** (Responses API, `openai/` + `api_base` customizado). As conversões de formato são feitas no proxy por serem o comportamento validado do código original (port de `chatgpt-openai-proxy` Bun/Hono) — o endpoint do plano ChatGPT fala Responses API com `store: false` obrigatório, e manter os conversores locais torna o comportamento testável e idêntico entre as engines. Se preferir tirar o LiteLLM do caminho, `UPSTREAM_ENGINE=httpx` usa o client direto.

## Testes

60 testes cobrindo: OAuth/PKCE/JWT, conversores (chat, responses, anthropic), streams SSE, credenciais (precedência + refresh), engines, endpoints HTTP (chat/responses/anthropic/admin/login) com o upstream Codex mockado.
