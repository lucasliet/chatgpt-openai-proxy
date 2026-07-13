# AGENTS.md

## Comandos canônicos

- Runtime é Bun; não trocar para `npm`, `yarn`, `jest` ou `vitest` sem uma migração explícita.
- Instalar dependências: `bun install`.
- Servidor local: `bun start` (`bun run src/index.ts`). Dev/watch: `bun run dev`.
- Login/status/logout: `bun run login`, `bun run status`, `bun run logout`.
- Verificação completa local/CI: `bun run typecheck` e depois `bun test`.
- CI usa `bun install --frozen-lockfile` -> `bun run typecheck` -> `bun test` em `.github/workflows/ci.yml`.
- Teste focado: `bun test tests/path/to/file.test.ts`.
- Não há script/config de lint ou formatter no repo; não inventar comandos inexistentes.

## Entry points e roteamento

- `src/index.ts` é o entrypoint CLI e servidor; sem argumento ele roda `serve`.
- `src/server/app.ts` monta o Hono app. Rotas públicas: `GET /health`, `/login/*`, `GET /v1/models`.
- `ensureToken()` protege só `/v1/responses*` e `/v1/chat/completions*`; monte novas rotas públicas antes dele.
- O stack HTTP é Hono em Bun (`Bun.serve`). Não introduza Express/Node HTTP sem intenção explícita.

## OAuth, login e credenciais

- O redirect OAuth real é `http://localhost:1455/auth/callback`; a porta 1455 é whitelisted pelo fluxo Codex. O env permite mudar `OAUTH_CALLBACK_PORT`, mas isso provavelmente quebra o OAuth real.
- Docker/Compose usam login web em `/login`: exponha só a porta 3000, abra a URL de autorização, aceite o `connection refused` no callback `localhost:1455`, copie a URL completa e cole em `/login`.
- O cookie `pkce` do login web é signed/httpOnly com `path: "/login"`; ao limpar, use o mesmo path e mantenha a validação de `state`.
- A URL OAuth é construída em dois fluxos: web (`src/auth/oauth-client.ts`) e CLI (`src/auth/login-server.ts`). Mantenha `client_id`, scope, redirect URI, `codex_cli_simplified_flow=true` e `originator=codex_cli_rs` sincronizados.
- Env vars de credenciais têm precedência sobre arquivo, mas só valem quando todas existem e `CHATGPT_EXPIRES_AT` é numérico: `CHATGPT_ACCESS_TOKEN`, `CHATGPT_REFRESH_TOKEN`, `CHATGPT_ACCOUNT_ID`, `CHATGPT_EXPIRES_AT`.
- Credenciais vindas de env são read-only: refresh não é persistido. Credenciais de arquivo ficam em `${CHATGPT_PROXY_HOME}/credentials.json` com diretório `0700` e arquivo `0600`.
- Nunca logue `accessToken`, `refreshToken`, `access_token` ou `refresh_token`.

## Config e TypeScript

- `config.oauthCallbackPort`, `config.codexBaseUrl`, `config.proxyHome` e `config.cookieSecret` são getters para permitir testes/env após import; não converta para valores eager. `config.port` é eager hoje.
- `tsconfig.json` é strict e inclui `noUncheckedIndexedAccess`, `noUnusedLocals` e `noUnusedParameters`; use guards ou `!` em acessos indexados quando necessário.
- Funções exportadas no código usam TSDoc; mantenha esse padrão e evite comentários inline explicativos no corpo da implementação.

## Conversores e compatibilidade OpenAI

- `convertChatToResponses` sempre deve enviar `store: false`.
- Preserve o fallback `"You are a helpful assistant."` quando não houver `system`/`developer`; o backend Codex rejeita `instructions` vazias.
- Mensagens `system` e `developer` viram `instructions` concatenadas com `\n\n`; `tool` vira `function_call_output`.
- `tools[].function` é achatado para `tools[].{name, description, parameters}`.
- `max_tokens` vira `max_output_tokens`; `max_completion_tokens` sobrescreve `max_tokens`.
- O stream converter deve emitir frames `data: {json}\n\n` e terminar com `data: [DONE]\n\n`.
- `/v1/models` expõe uma allowlist local, mas `isAllowedModel()` não bloqueia requests nas rotas de chat/responses.
- A API key enviada por clientes OpenAI-compatible é ignorada; autenticação upstream é só OAuth ChatGPT.

## Testes

- Testes usam `bun:test`; descrições atuais estão em português.
- Testes de auth mutam `process.env` e/ou `globalThis.fetch`; restaure valores em novos testes.
- Prefira injeção de dependências já existente (`deps` em rotas/middleware/clientes) a chamadas reais para ChatGPT/OpenAI.
- Testes do login CLI sobem servidor local em porta randômica via `OAUTH_CALLBACK_PORT`; evite hardcode de 1455 em testes unitários.

## Docker e deploy

- `docker-compose.yml` usa `ghcr.io/lucasliet/chatgptopenaiproxy:latest` com `pull_policy: always`, publica só `3000:3000` e monta `./data:/root/.config/chatgpt-proxy`.
- O container deve logar a rota `http://localhost:3000/login` no startup; mantenha essa orientação visível para usuários de Compose.
- `docker compose up -d` usa a imagem publicada; só use build local quando estiver validando o Dockerfile.
- Workflow de publish gera tags GHCR por run number, `latest` em `main`, semver em tags `v*.*.*` e `sha-<short>`.
- Atenção antes de mexer no build Docker: o repo tem `bun.lock`, enquanto o Dockerfile atual copia `bun.lockb*`; valide `docker build` se alterar publicação/imagem.
