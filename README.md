# chatgpt-openai-proxy

Proxy OpenAI-compatible que roteia chamadas para o endpoint privado do **ChatGPT Plan (Codex)** em `https://chatgpt.com/backend-api/codex/responses`, autenticando via **OAuth PKCE** com a conta ChatGPT (em vez de API key).

Permite que qualquer cliente OpenAI-existente (biblioteca `openai`, Cursor, Continue, etc.) use os modelos do ChatGPT Plan (`gpt-5.1-codex`, `gpt-5.2-codex`, etc.) apontando para o proxy.

## Endpoints expostos

| Rota                        | Descrição                                                         |
| --------------------------- | ----------------------------------------------------------------- |
| `POST /v1/chat/completions` | Converte Chat Completions → Responses API e devolve em formato OpenAI. |
| `POST /v1/responses`        | Passthrough direto para o Codex (sem conversão).                  |
| `GET /v1/models`            | Lista de modelos permitidos no ChatGPT Plan.                      |
| `GET /health`               | Healthcheck.                                                      |

## Pré-requisitos

- [Bun](https://bun.sh) >= 1.1
- Assinatura ChatGPT com acesso ao Codex (Plus/Pro/Team/Enterprise)

## Uso local

```bash
bun install

# 1. Autenticar uma vez (abre o navegador)
bun run login

# 2. Verificar estado das credenciais
bun run status

# 3. Subir o proxy
bun start
```

Aponte seu cliente OpenAI para `http://localhost:3000`:

```bash
curl http://localhost:3000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.1-codex",
    "messages": [{"role": "user", "content": "Olá!"}]
  }'
```

Com a biblioteca `openai` (Python):

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:3000/v1",
    api_key="chatgpt-plan",  # qualquer string; o proxy ignora a API key
)

resp = client.chat.completions.create(
    model="gpt-5.1-codex",
    messages=[{"role": "user", "content": "Olá!"}],
)
print(resp.choices[0].message.content)
```

## CLI

```text
chatgpt-openai-proxy

Comandos:
  serve    Inicia o servidor proxy (default)
  login    Executa o fluxo OAuth no navegador
  logout   Remove as credenciais salvas
  status   Mostra o estado atual das credenciais
  help     Exibe esta ajuda
```

## Variáveis de ambiente

| Variável                 | Default                                      | Descrição                                  |
| ------------------------ | -------------------------------------------- | ------------------------------------------ |
| `PORT`                   | `3000`                                       | Porta do servidor proxy.                   |
| `OAUTH_CALLBACK_PORT`    | `1455`                                       | Porta do callback OAuth (whitelisted).     |
| `CODEX_BASE_URL`         | `https://chatgpt.com/backend-api/codex`      | Endpoint do Codex.                         |
| `CHATGPT_PROXY_HOME`     | `~/.config/chatgpt-proxy`                    | Diretório base das credenciais.            |
| `CHATGPT_ACCESS_TOKEN`   | —                                            | Token via env (Docker headless).           |
| `CHATGPT_REFRESH_TOKEN`  | —                                            | Refresh token via env (Docker headless).   |
| `CHATGPT_ACCOUNT_ID`     | —                                            | Account id via env (Docker headless).      |
| `CHATGPT_EXPIRES_AT`     | —                                            | Expiração em ms via env (Docker headless). |

## Docker

O proxy pode rodar em container de três formas. **Variável chave: `OAUTH_CALLBACK_PORT=1455`** — essa porta é whitelisted no fluxo OAuth do Codex e não pode ser alterada.

### Modo 1: Importar tokens (recomendado para Docker headless)

Autentique numa máquina com browser (rodando o CLI local) e injete os tokens no container via env vars:

```bash
# Na máquina local com browser:
bun run login
bun run status  # mostra account_id e expiry
cat ~/.config/chatgpt-proxy/credentials.json
```

```bash
# No host headless via Docker:
docker run -d \
  -p 3000:3000 \
  -e CHATGPT_ACCESS_TOKEN='eyJ...' \
  -e CHATGPT_REFRESH_TOKEN='v1.MjQ1Nj...' \
  -e CHATGPT_ACCOUNT_ID='org-...' \
  -e CHATGPT_EXPIRES_AT='1748544000000' \
  chatgpt-openai-proxy
```

### Modo 2: OAuth no container com port-forward

Exponha ambas as portas. O fluxo OAuth roda dentro do container, mas **você abre a URL manualmente no browser do host** (o container não tem GUI):

```bash
docker run --rm -it -p 3000:3000 -p 1455:1455 chatgpt-openai-proxy login
# → copie a URL impressa e cole no navegador
# → o callback volta via port-forward para a porta 1455 do container

docker run -d -p 3000:3000 -p 1455:1455 -v ./data:/root/.config/chatgpt-proxy chatgpt-openai-proxy
```

### Modo 3: `--network host`

Para evitar problemas de port-forward em ambientes Linux:

```bash
docker run --network host chatgpt-openai-proxy
```

### docker-compose

```bash
docker compose up -d --build
```

Veja `docker-compose.yml` para as portas e volume padrão. Descomente as linhas de env vars para o modo headless.

## Modelo de autenticação

O fluxo OAuth 2.0 PKCE é o mesmo usado pelo Codex CLI:

1. Gera `code_verifier` + `code_challenge` (S256) + `state` aleatório.
2. Sobe um servidor HTTP em `http://localhost:1455/auth/callback`.
3. Abre `https://auth.openai.com/oauth/authorize?...` com:
   - `client_id=app_EMoamEEZ73f0CkXaXp7hrann`
   - `codex_cli_simplified_flow=true`
   - `originator=codex_cli_rs`
4. No callback, valida `state` (CSRF) e troca `code` por tokens.
5. Extrai `chatgpt_account_id` do `id_token` JWT.
6. Persiste `access_token`, `refresh_token`, `expires_at`, `account_id`.

**Refresh proativo**: antes de cada request, se o token expira em menos de 5 minutos, o middleware renova automaticamente e persiste o novo `refresh_token` se rotacionado.

## Segurança

- Arquivo de credenciais com permissão `0600`, diretório pai `0700`.
- `state` validado em todo callback OAuth (CSRF).
- PKCE sempre (nunca omitido).
- Refresh tokens são rotacionados quando o servidor retorna um novo.
- `access_token` nunca é logado.
- `account_id` é mascarado no comando `status`.

## Troubleshooting

### `Port 1455 already in use`

Outro processo (provavelmente o Codex CLI) está usando a porta. Feche-o ou ajuste `OAUTH_CALLBACK_PORT` (mas lembre que o fluxo OAuth do Codex espera `1455`).

### `connection refused` no callback OAuth dentro de Docker

O browser do host não alcança o container. Soluções:

- `docker run -p 1455:1455 ...` para port-forward da porta de callback.
- Ou `--network host` (Linux).
- Ou use o **Modo 1** (importação manual de tokens).

### `400 Bad Request: Instructions are not valid`

O Codex backend rejeita requests sem `instructions`. O proxy injeta `"You are a helpful assistant."` como fallback automaticamente quando o cliente não envia system message.

### `401 upstream_error` após algum tempo

O `access_token` expirou e o refresh falhou (ex: `refresh_token` revogado). Refaça o login: `bun run login`.

## Desenvolvimento

```bash
bun install
bun test          # 100 testes, estrutura AAA
bun run typecheck # tsc --noEmit strict
bun run dev       # watch mode
```

## Stack

- **Runtime:** Bun
- **Framework:** Hono
- **Linguagem:** TypeScript (strict)
- **Testes:** `bun:test`

## Referências

- [Reverse engineering Codex CLI](https://simonwillison.net/2025/Nov/9/gpt-5-codex-mini/) — Simon Willison
- [Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events/) — OpenAI API Reference
- [Codex CLI remote OAuth issue](https://github.com/openai/codex/issues/2798)
