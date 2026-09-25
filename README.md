# chatgpt-openai-proxy

Proxy **OpenAI + Anthropic** compatível, em **FastAPI**, que deixa cada usuário usar a **própria assinatura do ChatGPT (Codex)** via OAuth — cada login gera uma **API key** que passa a ser a credencial de acesso ao proxy. Pronto para deploy no **[FastAPI Cloud](https://fastapicloud.com)**.

## Como funciona

```
cliente ──Bearer sk-...──▶ proxy ──OAuth do dono da key──▶ ChatGPT Plan (Codex)
```

1. O usuário abre **`/login`** e autentica a **própria conta ChatGPT** (OAuth PKCE, com modo "colar URL de callback" para headless/Docker)
2. O proxy salva os tokens OAuth **atrelados ao usuário** no banco e gera uma **API key aleatória** (`sk-...`), exibida **uma única vez**
3. Toda chamada à API com essa key usa a **assinatura daquele usuário**; o access token é renovado automaticamente (buffer de 5 min, refresh token rotacionado e persistido)
4. **Re-login na mesma conta** (token venceu ou key foi perdida) renova os tokens, **revoga as keys antigas** e exibe uma nova

## Features

- **Três formatos de entrada**: `POST /v1/responses` (passthrough), `POST /v1/chat/completions` e `POST /v1/messages` (Anthropic, com streaming SSE nos eventos oficiais) — conversões bidirecionais fieis ao proxy original
- **Multi-conta**: cada usuário com sua assinatura; tokens isolados por usuário, refresh com lock por conta
- **API keys** com hash SHA-256 (a chave completa nunca é armazenada), revogação e `last_used_at`
- **Engine upstream intercambiável**: [LiteLLM](https://docs.litellm.ai/docs/response_api) (default) ou HTTPX direto (`UPSTREAM_ENGINE=httpx`)
- **Banco agnóstico**: Postgres (Neon/Supabase) em produção; sem `DATABASE_URL`, arquivo SQLite em `CHATGPT_PROXY_HOME` — mesmo modelo do projeto anterior para run local/Docker

## Quick start local

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e Python 3.12.

```bash
uv sync
uv run fastapi dev
```

Abra `http://localhost:3000/login`, autorize com sua conta ChatGPT e **copie a API key exibida**. Use essa key nas chamadas. Sem `DATABASE_URL`, tudo fica em `~/.config/chatgpt-proxy/proxy.db` (override via `CHATGPT_PROXY_HOME`; em Docker, monte o diretório como volume).

## Deploy no FastAPI Cloud

O projeto segue as convenções da plataforma (entrypoint em `[tool.fastapi]`, `fastapi[standard]`, `.python-version`, `.fastapicloudignore`):

```bash
uvx fastapi login
fastapi cloud env set --secret ADMIN_API_KEY "sk-admin-segura"
fastapi cloud env set --secret COOKIE_SECRET "segredo-aleatorio"
fastapi deploy
```

Depois conecte um banco gerenciado pelo dashboard (**Neon integration**) — o `DATABASE_URL` é injetado automaticamente. As tabelas são criadas (e migradas, com `ALTER TABLE` idempotente) no boot de cada instância, seguro para autoscaling e zero-downtime.

## Uso

### Login e API key

```bash
# No navegador: https://<seu-app>.fastapicloud.dev/login
# Ao concluir, a página exibe a API key (uma única vez):
export KEY="sk-..."
```

Para gerar key de outra forma ou gerenciar usuários (admin):

```bash
ADMIN_KEY="sk-admin-segura"   # definida no deploy
curl https://<app>.fastapicloud.dev/admin/users -H "X-Admin-Key: $ADMIN_KEY"
curl -X POST https://<app>.fastapicloud.dev/admin/users/1/keys -H "X-Admin-Key: $ADMIN_KEY" -d '{"label": "notebook"}'
```

Endpoints admin: `GET/POST/DELETE /admin/users[...]` · `GET/POST /admin/users/{id}/keys` · `POST /admin/keys/{id}/revoke`. A listagem mostra o status da credencial OAuth de cada usuário (autenticado, expiração, último login).

### Chamar a API

```bash
export KEY="sk-..."

curl https://<app>.fastapicloud.dev/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-6-luna", "messages": [{"role": "user", "content": "oi"}]}'

curl https://<app>.fastapicloud.dev/v1/responses \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-6-luna", "input": "oi", "store": false}'

curl https://<app>.fastapicloud.dev/v1/messages \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-4-5", "max_tokens": 1024, "messages": [{"role": "user", "content": "oi"}]}'
```

Streaming (`"stream": true`) funciona nos três endpoints.

Compatibilidade com clientes oficiais:

```python
from openai import OpenAI
client = OpenAI(base_url="https://<app>.fastapicloud.dev/v1", api_key="sk-...")
client.chat.completions.create(model="gpt-6-luna", messages=[...])
```

```python
import anthropic
client = anthropic.Anthropic(base_url="https://<app>.fastapicloud.dev", api_key="sk-...")
client.messages.create(model="claude-sonnet-4-5", max_tokens=1024, messages=[...])
# modelos claude-* caem no DEFAULT_MODEL (gpt-6-luna) upstream
```

## Configuração

| Env var | Default | Descrição |
| --- | --- | --- |
| `PORT` | `3000` | Porta do servidor |
| `DATABASE_URL` | — (SQLite local) | Postgres em produção; sem definir, usa `CHATGPT_PROXY_HOME/proxy.db` |
| `CHATGPT_PROXY_HOME` | `~/.config/chatgpt-proxy` | Diretório do armazenamento local |
| `UPSTREAM_ENGINE` | `litellm` | `litellm` (default) ou `httpx` |
| `DEFAULT_MODEL` | `gpt-6-luna` | Modelo quando o pedido está fora da allowlist |
| `ADMIN_API_KEY` | — (gerada no boot) | Chave dos endpoints `/admin/*` |
| `COOKIE_SECRET` | dev | Segredo do cookie de sessão do `/login` |
| `CODEX_BASE_URL` | `https://chatgpt.com/backend-api/codex` | Backend do plano ChatGPT |

## Docker

```bash
docker compose up -d
```

O compose monta `./data:/root/.config/chatgpt-proxy` — o armazenamento local sobrevive a recriações do container.

## Desenvolvimento

```bash
uv sync                 # instala deps (inclui grupo dev)
uv run pytest           # 67 testes (upstream Codex mockado com respx)
uv run fastapi dev      # servidor com reload
```

Arquitetura:

```
app/
├── main.py            # app FastAPI, lifespan, exception handler
├── config.py          # settings via env (pydantic-settings)
├── database.py        # engine, init idempotente, migração de colunas
├── models.py          # User (com tokens OAuth), ApiKey (SQLModel)
├── security.py        # geração/hash de keys, auth admin
├── oauth.py           # PKCE, troca/refresh de token, JWT (account_id, email)
├── credentials.py     # refresh por usuário (lock por conta)
├── codex.py           # engines LiteLLM/HTTPX
├── deps.py            # auth: API key → usuário → credencial
├── allowlist.py       # fallback estático de modelos (usado se o /models do backend falhar)
├── converters/        # chat↔responses, SSE, anthropic↔chat
└── routers/           # login, admin, models, responses, chat, anthropic
```

## Segurança dos tokens

Os tokens OAuth ficam em texto no banco, isolados por usuário — mesmo nível do `credentials.json` 0600 do projeto original. Para produção séria, considere cifrar em repouso; as chaves de API, em contraste, só existem como hash.

## Por que não LiteLLM nos conversores?

O LiteLLM é a **engine upstream** (Responses API, `openai/` + `api_base` customizado). As conversões de formato ficam no proxy por serem o comportamento validado do código original — o endpoint do plano ChatGPT fala Responses API com `store: false` obrigatório. `UPSTREAM_ENGINE=httpx` remove o LiteLLM do caminho (cold start mais leve).

## Testes

66 testes: OAuth/PKCE/JWT, conversores, streams SSE, credenciais por usuário (refresh isolado), engines, endpoints HTTP e fluxos de login/re-login — tudo com o upstream Codex mockado.
