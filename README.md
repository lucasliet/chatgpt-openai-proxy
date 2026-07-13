# chatgpt-openai-proxy

Proxy OpenAI-compatible que roteia chamadas para o endpoint privado do **ChatGPT Plan (Codex)** em `https://chatgpt.com/backend-api/codex/responses`, autenticando via **OAuth PKCE** com a conta ChatGPT (em vez de API key).

Permite que qualquer cliente OpenAI-existente (biblioteca `openai`, Cursor, Continue, etc.) use os modelos do ChatGPT Plan (`gpt-5.1-codex`, `gpt-5.2-codex`, etc.) apontando para o proxy.

## Endpoints expostos

| Rota                        | Descrição                                                         |
| --------------------------- | ----------------------------------------------------------------- |
| `GET /login`                | Tela de login web (UI HTML) para autenticar via browser.          |
| `POST /login/start`         | Inicia o fluxo OAuth PKCE, retorna a URL de autorização.          |
| `POST /login/complete`      | Finaliza o login recebendo a URL de callback colada pelo usuário.  |
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

# 1. Subir o proxy
bun start

# 2. Autenticar via browser: abra http://localhost:3000/login
#    (ou use o CLI: bun run login)

# 3. Verificar estado das credenciais
bun run status
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
| `COOKIE_SECRET`          | `chatgpt-proxy-dev-secret`                   | Segredo do cookie PKCE do login web.       |
| `CHATGPT_ACCESS_TOKEN`   | —                                            | Token via env (Docker headless).           |
| `CHATGPT_REFRESH_TOKEN`  | —                                            | Refresh token via env (Docker headless).   |
| `CHATGPT_ACCOUNT_ID`     | —                                            | Account id via env (Docker headless).      |
| `CHATGPT_EXPIRES_AT`     | —                                            | Expiração em ms via env (Docker headless). |

## Docker

O proxy roda em container e oferece **3 modos de autenticação**. O modo web (recomendado) funciona em qualquer ambiente — não precisa de porta 1455 nem de CLI dentro do container.

### Modo 1: Login web (recomendado para qualquer ambiente)

Basta expor a porta 3000. O login acontece no browser:

```bash
docker run -d -p 3000:3000 -v ./data:/root/.config/chatgpt-proxy ghcr.io/lucasliet/chatgptopenaiproxy:latest
```

Depois:

1. Abra `http://localhost:3000/login` no navegador.
2. Clique em **"Iniciar login com ChatGPT"** — o proxy gera a URL de autorização.
3. Abra o link e autorize no ChatGPT. O browser tentará redirecionar para `localhost:1455/auth/callback?code=...&state=...` e pode mostrar erro de conexão — **isso é normal**.
4. Copie a **URL completa** da barra de endereços do navegador.
5. Cole a URL no campo da tela de login e clique em **"Concluir login"**.

As credenciais são persistidas no volume `./data`, então o login é feito apenas uma vez.

### Modo 2: Importar tokens via env (headless puro)

Se não há browser no host, autentique numa máquina com browser (rodando o proxy localmente) e injete os tokens no container via env vars:

```bash
# Na máquina com browser:
bun start  # ou docker run -p 3000:3000 ghcr.io/lucasliet/chatgptopenaiproxy:latest
# → faça login em /login e copie o conteúdo de data/credentials.json
cat data/credentials.json
```

```bash
# No host headless:
docker run -d \
  -p 3000:3000 \
  -e CHATGPT_ACCESS_TOKEN='eyJ...' \
  -e CHATGPT_REFRESH_TOKEN='v1.MjQ1Nj...' \
  -e CHATGPT_ACCOUNT_ID='org-...' \
  -e CHATGPT_EXPIRES_AT='1748544000000' \
  ghcr.io/lucasliet/chatgptopenaiproxy:latest
```

### Modo 3: `--network host` (Linux)

Evita problemas de port-forward; o callback `localhost:1455` funciona naturalmente:

```bash
docker run --network host ghcr.io/lucasliet/chatgptopenaiproxy:latest
```

### docker-compose

```bash
docker compose up -d
docker compose logs -f chatgpt-proxy
```

O container usa `ghcr.io/lucasliet/chatgptopenaiproxy:latest` e imprime nos logs a rota `http://localhost:3000/login` para autenticação. Veja `docker-compose.yml` para portas e volume padrão.

## Modelo de autenticação

O fluxo OAuth 2.0 PKCE é o mesmo usado pelo Codex CLI:

1. Gera `code_verifier` + `code_challenge` (S256) + `state` aleatório.
2. Monta `https://auth.openai.com/oauth/authorize?...` com:
   - `client_id=app_EMoamEEZ73f0CkXaXp7hrann`
   - `codex_cli_simplified_flow=true`
   - `originator=codex_cli_rs`
   - `redirect_uri=http://localhost:1455/auth/callback` (whitelisted)
3. Usuário autoriza no ChatGPT → browser redireciona para `localhost:1455/auth/callback?code=...&state=...`.
4. **Modo web:** o usuário cola essa URL na tela `/login` → o proxy valida `state` (CSRF), troca `code` por tokens. **Modo CLI:** o proxy captura automaticamente via servidor na porta 1455.
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

**Isso é esperado no modo web.** O browser tenta abrir `localhost:1455` mas o container não está ouvindo essa porta — a solução é copiar a URL completa da barra de endereços e colar na tela de `/login`. Veja "Modo 1: Login web" acima.

Alternativas:

- `--network host` (Linux) — o callback funciona naturalmente.
- Modo env vars (importar tokens manuais).

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
