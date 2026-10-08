# AGENTS.md

## Comandos canônicos

- Gerenciador de pacotes é **uv**; não usar `pip` direto nem trocar para outro runtime sem migração explícita.
- Instalar dependências: `uv sync` (inclui grupo dev; lock em `uv.lock` — manter atualizado com `uv lock`).
- Servidor local: `uv run fastapi dev` (reload). Produção: `uv run uvicorn app.main:app --host 0.0.0.0 --port 3000`.
- Verificação completa local/CI: `uv run pytest`.
- CI usa `uv sync --frozen` -> `uv run pytest` em `.github/workflows/ci.yml`.
- Lint/format: `uv run ruff check app tests` e `uv run ruff format app tests` (config em `[tool.ruff]` no `pyproject.toml`, line-length 100; CI roda `check` e `format --check` antes dos testes).
- Teste focado: `uv run pytest tests/test_api.py::TestLoginFlow`.

## Modelo de autenticação (não quebrar)

- **OAuth é por usuário**: cada usuário autentica a própria conta ChatGPT via `/login`; os tokens ficam na linha de `proxy_user` e a API key gerada no login é a credencial de acesso ao proxy. Não existe credencial global compartilhada nem env vars `CHATGPT_*`.
- Re-login na mesma conta (identificada pelo `account_id` do id_token) faz upsert dos tokens, **revoga as keys antigas** e exibe uma nova. Re-login nunca duplica usuário.
- As rotas de proxy resolvem a cadeia: Bearer key → `ApiKey` (hash SHA-256 com salt) → `User` → credencial OAuth daquele usuário (com refresh pró-ativo de 5 min, lock por usuário).
- Clientes Anthropic usam o wire format Messages; o `model` é repassado ao upstream como nos demais endpoints — precisa ser um modelo do ChatGPT Plan.
- Tokens OAuth (`access_token`/`refresh_token`) são **cifrados em repouso** via `EncryptedText` (`app/crypto.py`, Fernet). `TOKEN_ENCRYPTION_KEY` aceita lista separada por vírgula (rotação: a primeira cifra, todas decifram). Com `DATABASE_URL` a env é obrigatória (boot falha sem ela); sem ela e sem DATABASE_URL, keyfile `token.key` 0600 no proxy home. `init_db()` migra texto puro legado e rotaciona chaves antigas — manter idempotência.
- `GET /` serve a landing page/documentação de uso embutida; `GET /logout` renderiza a página de confirmação e `POST /logout` (com Bearer key) faz hard delete do usuário + credenciais OAuth + todas as suas API keys — irreversível; voltar exige novo `/login`.
- **UI é SSR-first**: páginas são HTML renderizado no servidor. Não é proibição de JS — cada comportamento fica onde for melhor: no servidor quando SSR resolve (conteúdo, dados, fragmentos como o partial de período e os limites da assinatura), no cliente quando a interatividade exige (tema, hold-to-confirm, copiar key, OAuth headless com colar de callback, tooltip do gráfico) ou quando cosmética/otimização é mais natural no browser (ex.: pausar animação do diagrama fora da tela via IntersectionObserver). JS de cosmética/otimização é aceitável se justificado — nunca remover feature só para reduzir JS; a decisão é onde cada coisa mora.
- **Backoffice web**: `/admin-login` valida a `ADMIN_API_KEY` (mesma da API JSON) e grava cookie de sessão admin assinado (HMAC-SHA256 com `COOKIE_SECRET`, httponly, SameSite=Lax, 12h). `/backoffice` e filhos exigem esse cookie via `require_admin_session` — sem ele, 303 para `/admin-login` (o handler de `HTTPException` em `main.py` converte 3xx+Location em redirect). As ações do backoffice reutilizam os handlers de `app/routers/admin.py` para não divergir; a API JSON `/admin/*` continua com `X-Admin-Key`.
- **Ações destrutivas na UI** (`/logout`, revogar key e excluir usuário no backoffice) exigem hold-to-confirm de 2s — sem `confirm()` nativo. O CSS `.btn.hold` e o `HOLD_CONFIRM_SCRIPT` (botões `type="button"` com `data-hold-confirm`) ficam em `app/routers/theme.py`. Com `prefers-reduced-motion` só o feedback visual muda (opacidade em vez de varredura); a espera de 2s nunca encurta.
- **Dashboard do usuário**: `/dashboard/login` recebe a API key do proxy por formulário POST; nunca cria usuário, salva credenciais OAuth ou emite/revoga API keys. Reutiliza a autenticação Bearer, que atualiza `last_used_at`. Cookie `dashboard_session` assinado, 12h; identidade inclui criação da conta e ID da key para impedir reuso após exclusão e invalidar a sessão na revogação. A chave completa não fica no cookie nem no armazenamento do navegador. `COOKIE_SECRET` aleatório de pelo menos 32 caracteres é obrigatório para habilitar o fluxo. Consultas sempre usam o usuário da sessão, nunca `user_id` recebido do cliente. `/dashboard/logout` só encerra a sessão.
- O formulário do dashboard exige token CSRF vinculado à sessão web assinada, validado antes de autenticar a API key. Tokens inválidos/expirados não podem trocar a identidade nem atualizar `last_used_at`. Formulários, redirects e navegação do dashboard preservam `root_path`, inclusive com mounts nomeados.
- **Limites Codex**: `/v1/usage` exige Bearer key; `/dashboard/limits` exige a sessão do usuário. Ambos usam `SubscriptionService` com OAuth daquele usuário e refresh existente. Não contam como chamadas de IA. A resposta é uma projeção tipada de `wham/usage`, nunca o JSON bruto nem email/IDs/tokens. Cache apenas efêmero por instância, 60s (falhas 10s, sem credencial não cacheia), 256 entradas; identidade inclui criação da conta. Requisições simultâneas do mesmo usuário são agrupadas em uma única consulta. Seções opcionais malformadas viram `None` sem invalidar o `rate_limit` principal; só ele inválido retorna indisponível. Nada depende de compartilhar cache entre réplicas. Falhas retornam dados indisponíveis, nunca zero; o painel local funciona mesmo quando o upstream falha. `CODEX_USAGE_URL` é independente da engine. Testes sempre mockam essa URL.

## Telemetria mínima

- `app/telemetry.py` captura `usage` do Codex antes dos conversores, nos três endpoints, streaming ou não. Persistir apenas agregados por usuário/hora UTC/modelo efetivo, sem conteúdo, IPs, payloads ou ferramentas. Ausência de `usage` é desconhecida, não consumo medido de zero.
- `proxy_usage` usa upsert atômico e FK `ON DELETE CASCADE`. A captura inclui a criação da conta para descartar escritas de streams após exclusão/recriação. Cache integra tokens de entrada; reasoning integra saída — não somar novamente.
- Retenção de 30 dias, limpeza no boot e a cada hora enquanto ativo. Painéis em `/dashboard` e `/backoffice/users/{id}/usage` compartilham renderização e filtros Hoje/7/30 dias.
- `app/pricing.py` busca catálogo público OpenAI do models.dev a cada 24h, persistido no banco; falhas preservam catálogo anterior. `PRICING_ENABLED=false` desliga fetch, não telemetria. Custos históricos em USD não são recalculados; modelos sem preço exato ficam sem estimativa. Testes não consultam o catálogo real nem providers reais.

## FastAPI Cloud

- Deploy alvo: https://fastapicloud.com/docs/ — entrypoint em `[tool.fastapi] entrypoint = "app.main:app"` no `pyproject.toml`.
- `fastapi[standard]` deve permanecer em dependencies (CLI de deploy da plataforma).
- Python pinado em `.python-version` (3.12) e `requires-python` no pyproject.
- Config 100% por env vars (pydantic-settings); nada de segredos em arquivo versionado.
- A plataforma faz autoscaling multi-instância com deploys zero-downtime: nada de estado em disco/memória compartilhado. Em produção `DATABASE_URL` vem da integração Neon. `init_db()` usa `create_all` + migração de colunas idempotente (`_USER_COLUMN_MIGRATIONS`) — não quebrar a idempotência.
- Se `ADMIN_API_KEY` não estiver definida, uma chave é gerada por instância no boot (impressa nos logs). Em produção multi-instância a env é obrigatória.
- **Acompanhar deploy após push na main**: o push dispara deploy automático (integração GitHub do FastAPI Cloud); sempre conferir: aguardar ~1 min, rodar `uv run fastapi cloud deployments list` e `uv run fastapi cloud deployments get <id-do-mais-recente>` até o status ficar `success`. Se falhar, ver `uv run fastapi cloud deployments build-logs <id>` e logs do app em `uv run fastapi cloud logs` (`--no-follow` para buscar e sair). `uv run fastapi deploy` sem `--no-wait` já aguarda o status até concluir.

## Storage local (sem DATABASE_URL)

- Sem `DATABASE_URL`, o estado vai para `sqlite:///{CHATGPT_PROXY_HOME}/proxy.db` (default `~/.config/chatgpt-proxy`, mesma função do `credentials.json` do projeto anterior). Diretório `0700`, arquivo `0600` — manter.
- Docker/Compose monta o diretório como volume; não reintroduzir paths absolutos fora do proxy home.

## OAuth e conversores

- Redirect OAuth real é `http://localhost:1455/auth/callback`; a porta é configurável via `OAUTH_CALLBACK_PORT` mas mudá-la provavelmente quebra o fluxo (whitelisting Codex).
- `chat_to_responses` sempre envia `store: false`; fallback `"You are a helpful assistant."` quando não há system/developer (backend rejeita `instructions` vazio).
- system/developer → `instructions` com `\n\n`; `tool` → `function_call_output`; `tools[].function` achatado; `max_completion_tokens` sobrescreve `max_tokens`.
- `reasoning_effort`/`reasoning.effort` do Chat Completions é repassado como `reasoning.{effort}` — sem isso o backend trata reasoning como ativo e rejeita `temperature != 1`. Com effort `none` o `temperature` é dropado (backend rejeita o parâmetro em qualquer valor).
- Streams de chat terminam com `data: [DONE]\n\n`; streams Anthropic usam linha `event:` (`message_start`/`content_block_*`/`message_delta`/`message_stop`).
- Engine upstream em `app/codex.py`: `LiteLLMEngine` (default) e `HttpxEngine` (`UPSTREAM_ENGINE=httpx`), mesma interface (`responses` / `responses_stream`).

## Testes

- Testes usam `pytest` + `pytest-asyncio` (modo auto) + `respx` para mockar o upstream Codex (`tests/conftest.py` força `UPSTREAM_ENGINE=httpx`).
- Fixtures constroem um app fresco por teste com SQLite em tmp path e env isolada (cuidado com os caches — usar `get_settings.cache_clear()` + `database.reset_engine()` + `crypto.reset_keyring()`).
- `tests/conftest.py` tem `create_user_with_credentials`/`create_api_key` para simular contas OAuth; fixtures de env globais de credencial foram removidas de propósito.
- Ao adicionar env vars novas em `Settings`, refletir em `.env.example`, README e `tests/conftest.py::_setup_env` quando aplicável.
