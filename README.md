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
- **Tokens OAuth cifrados em repouso** (Fernet — AES-128-CBC + HMAC): no banco só existe ciphertext. A chave vem de `TOKEN_ENCRYPTION_KEY` (aceita lista separada por vírgula para rotação); sem `DATABASE_URL`, uma chave é gerada em `CHATGPT_PROXY_HOME/token.key` (0600)
- **Engine upstream intercambiável**: [LiteLLM](https://docs.litellm.ai/docs/response_api) (default) ou HTTPX direto (`UPSTREAM_ENGINE=httpx`)
- **Banco agnóstico**: Postgres (Neon/Supabase) em produção; sem `DATABASE_URL`, arquivo SQLite em `CHATGPT_PROXY_HOME` — mesmo modelo do projeto anterior para run local/Docker

## Quick start local

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e Python 3.12.

```bash
uv sync
uv run fastapi dev
```

Abra `http://localhost:3000/login`, autorize com sua conta ChatGPT e **copie a API key exibida**. Use essa key nas chamadas. Sem `DATABASE_URL`, tudo fica em `~/.config/chatgpt-proxy/proxy.db` (override via `CHATGPT_PROXY_HOME`; em Docker, monte o diretório como volume).

A raiz do app (`GET /`) serve a **landing page** do projeto: documentação de uso embutida no próprio servidor (login, API key, rotação de keys, endpoints, tradução para Responses API e logout) — útil em deploy, onde não há README à mão.

## Deploy no FastAPI Cloud

O projeto segue as convenções da plataforma (entrypoint em `[tool.fastapi]`, `fastapi[standard]`, `.python-version`, `.fastapicloudignore`):

```bash
uvx fastapi login
fastapi cloud env set --secret ADMIN_API_KEY "sk-admin-segura"
fastapi cloud env set --secret COOKIE_SECRET "segredo-aleatorio"
fastapi cloud env set --secret TOKEN_ENCRYPTION_KEY "$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
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

O mesmo gerenciamento existe em interface web: **`/admin-login`** (entre com a `ADMIN_API_KEY`) abre sessão de 12h e libera o **`/backoffice`** — listagem de usuários com status da credencial e keys, criação de usuário, emissão/revogação de keys e remoção de usuários. Todas as rotas `/backoffice` exigem o cookie de sessão admin; sem ele, redirecionam para o login.

### Rotação de API key

Perdeu a key ou ela venceu? Basta refazer o `/login` com a mesma conta ChatGPT: o proxy faz upsert dos tokens OAuth, **revoga as keys antigas** e exibe uma nova (fluxo descrito em "Como funciona"). Para revogar uma key sem trocar as demais, use `POST /admin/keys/{id}/revoke`.

### Logout e exclusão de dados

`GET /logout` renderiza uma página para colar a API key e confirmar. `POST /logout` com a key autenticada **remove permanentemente do banco** o usuário dono da key, suas credenciais OAuth e **todas as suas API keys** — como se a conta nunca tivesse sido cadastrada. A key para de funcionar imediatamente (passa a responder 401):

```bash
curl -X POST https://<app>.fastapicloud.dev/logout \
  -H "Authorization: Bearer $KEY"
# {"success": true, "message": ...}
```

A exclusão é **irreversível**. Para voltar a usar o proxy, é preciso um novo `/login` — a conta é recriada do zero, com uma nova API key.

### Chamar a API

```bash
export KEY="sk-..."

curl https://<app>.fastapicloud.dev/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "oi"}]}'

curl https://<app>.fastapicloud.dev/v1/responses \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-6.1-sol", "input": "oi", "store": false}'

curl https://<app>.fastapicloud.dev/v1/messages \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-6.1-sol", "max_tokens": 1024, "messages": [{"role": "user", "content": "oi"}]}'
```

Streaming (`"stream": true`) funciona nos três endpoints.

O endpoint Anthropic aceita o wire format Messages, mas o modelo upstream continua sendo do ChatGPT Plan. Se o cliente mandar um nome fora da allowlist (ex.: `claude-*`), o proxy usa `DEFAULT_MODEL` (`gpt-6.1-sol` por padrão) e ecoa o nome pedido na resposta.

Compatibilidade com clientes oficiais:

```python
from openai import OpenAI
client = OpenAI(base_url="https://<app>.fastapicloud.dev/v1", api_key="sk-...")
client.chat.completions.create(model="gpt-6.1-sol", messages=[...])
```

```python
import anthropic
client = anthropic.Anthropic(base_url="https://<app>.fastapicloud.dev", api_key="sk-...")
client.messages.create(model="gpt-6.1-sol", max_tokens=1024, messages=[...])
```

## Configuração

| Env var | Default | Descrição |
| --- | --- | --- |
| `PORT` | `3000` | Porta do servidor |
| `DATABASE_URL` | — (SQLite local) | Postgres em produção; sem definir, usa `CHATGPT_PROXY_HOME/proxy.db` |
| `CHATGPT_PROXY_HOME` | `~/.config/chatgpt-proxy` | Diretório do armazenamento local |
| `UPSTREAM_ENGINE` | `litellm` | `litellm` (default) ou `httpx` |
| `DEFAULT_MODEL` | `gpt-6.1-sol` | Modelo upstream quando o pedido está fora da allowlist (ex.: `claude-*`) |
| `ADMIN_API_KEY` | — (gerada no boot) | Chave dos endpoints `/admin/*` |
| `COOKIE_SECRET` | dev | Segredo do cookie de sessão do `/login` |
| `CODEX_BASE_URL` | `https://chatgpt.com/backend-api/codex` | Backend do plano ChatGPT |

## Docker

```bash
docker compose up -d
```

O compose monta `./data:/data` (`CHATGPT_PROXY_HOME` da imagem) — `proxy.db` **e** o `token.key` (chave que cifra os tokens OAuth, gerada com 0600 no primeiro boot) sobrevivem a recriações do container. Para usar Postgres no lugar do SQLite, defina `DATABASE_URL` **e** `TOKEN_ENCRYPTION_KEY` (obrigatória nesse modo — sem ela o boot falha).

## Desenvolvimento

```bash
uv sync                 # instala deps (inclui grupo dev)
uv run pytest           # 105 testes (upstream Codex mockado com respx)
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

Os tokens OAuth (`access_token`/`refresh_token`) são **cifrados em repouso** com Fernet (AES-128-CBC + HMAC) via `EncryptedText` (`app/crypto.py`) — no banco só existe ciphertext. A chave vem de `TOKEN_ENCRYPTION_KEY` (aceita lista separada por vírgula para rotação: a primeira cifra, todas decifram); sem `DATABASE_URL`, uma chave é gerada em `CHATGPT_PROXY_HOME/token.key` (0600). Com `DATABASE_URL` definida a env é **obrigatória** — instâncias efêmeras não podem gerar chave própria, senão cada uma gravaria tokens ilegíveis para as outras. As API keys, por sua vez, só existem como hash SHA-256 com salt.

## Por que não LiteLLM nos conversores?

O LiteLLM é a **engine upstream** (Responses API, `openai/` + `api_base` customizado). As conversões de formato ficam no proxy por serem o comportamento validado do código original — o endpoint do plano ChatGPT fala Responses API com `store: false` obrigatório. `UPSTREAM_ENGINE=httpx` remove o LiteLLM do caminho (cold start mais leve).

## Testes

105 testes: OAuth/PKCE/JWT, conversores, streams SSE, credenciais por usuário (refresh isolado), engines, criptografia dos tokens em repouso, endpoints HTTP e fluxos de login/re-login — tudo com o upstream Codex mockado.
