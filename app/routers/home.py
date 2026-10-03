"""Landing page e documentação de uso — ``GET /``.

Renderiza uma página HTML self-contained que documenta o proxy: como funciona
o login OAuth, como usar a API key nas chamadas OpenAI/Anthropic, as regras
de tradução para a Responses API do Codex e o fluxo de logout/exclusão de
dados. O CSS base vem de ``app/routers/theme.py`` (design system compartilhado
com /login e /logout); aqui ficam só os estilos específicos (hero, diagrama
de tradução e índice).
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .theme import (
    BASE_CSS,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home_page():
    return _render_home_html()


_PAGE_CSS = """
.hero { padding: 3rem 0 1.5rem; }
.hero h1 { font-size: clamp(2.3rem, 5.5vw, 3.6rem); font-weight: 700; margin: 0 0 1rem; max-width: 18ch; }
.hero .sub { color: var(--muted); font-size: 1.05rem; max-width: 58ch; margin: 0; }
.hero .actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1.6rem; }

.diagram { margin: 2.5rem 0 0; }
.diagram svg { width: 100%; height: auto; display: block; }
.diagram .node { fill: var(--surface); stroke: var(--line); }
.diagram .node-accent { fill: var(--surface); stroke: var(--link); }
.diagram .node-term { fill: var(--term-bg); stroke: var(--term-bg); }
.diagram .t-label { font-family: var(--font-mono); font-size: 12.5px; fill: var(--ink); }
.diagram .t-dim { font-family: var(--font-mono); font-size: 10.5px; fill: var(--muted); }
.diagram .t-accent { font-family: var(--font-mono); font-size: 12.5px; fill: var(--link); }
.diagram .t-term { font-family: var(--font-mono); font-size: 12.5px; fill: var(--term-accent); }
.diagram .t-termdim { font-family: var(--font-mono); font-size: 10.5px; fill: var(--term-dim); }
.flow-line {
  stroke: var(--link);
  stroke-width: 1.5;
  stroke-dasharray: 6 6;
  animation: march 1.1s linear infinite;
}
@keyframes march { to { stroke-dashoffset: -12; } }

.index {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.3rem;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  padding: 0.9rem 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  margin: 2.5rem 0 1.5rem;
}
.index a { color: var(--muted); text-decoration: none; }
.index a:hover { color: var(--link); }
.index .n { color: var(--link); margin-right: 0.35em; }

section[id] { scroll-margin-top: 1.5rem; }
.panel ol, .panel ul { margin: 0.5rem 0; padding-left: 1.4rem; }
.panel li { margin: 0.3rem 0; }
.panel p { margin: 0.5rem 0; }
"""


def _render_home_html() -> str:
    return (
        """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Docs</title>
  """
        + THEME_HEAD_SCRIPT
        + """<style>"""
        + BASE_CSS
        + _PAGE_CSS
        + THEME_TOGGLE_CSS
        + """</style>
</head>
<body>
  <div class="container">
    <header class="topbar">
      <a class="brand" href="/">chatgpt-openai-proxy</a>
      <nav>
        <a href="/login">/login</a>
        <a href="/logout">/logout</a>
        <a href="/health">/health</a>
        """
        + THEME_TOGGLE_HTML
        + """
      </nav>
    </header>

    <div class="hero rise" style="--d: 0">
      <p class="eyebrow"><span class="tick">///</span> SUA ASSINATURA CHATGPT VIA API KEY — OPENAI · ANTHROPIC · RESPONSES</p>
      <h1>Uma assinatura ChatGPT. Três protocolos.</h1>
      <p class="sub">
        Autentique sua conta via OAuth, receba uma API key e use a <strong>sua
        assinatura</strong> em qualquer cliente: o proxy fala a Responses API
        nativamente e ainda traduz Chat Completions e Anthropic Messages para ela.
      </p>
      <div class="actions">
        <a class="btn" href="/login">Fazer login</a>
        <a class="btn ghost" href="#endpoints">Ver endpoints</a>
      </div>
    </div>

    <div class="diagram rise" style="--d: 1" role="img" aria-label="Diagrama: requisições Chat Completions, Responses API e Anthropic Messages entram no proxy — que traduz e autentica com a sua assinatura — e saem como Responses API do Codex">
      <svg viewBox="0 0 760 290" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect class="node" x="8" y="14" width="212" height="46" rx="6"/>
        <text class="t-label" x="22" y="34">POST /v1/chat/completions</text>
        <text class="t-dim" x="22" y="50">OpenAI · chat</text>
        <rect class="node" x="8" y="122" width="212" height="46" rx="6"/>
        <text class="t-label" x="22" y="142">POST /v1/responses</text>
        <text class="t-dim" x="22" y="158">OpenAI · passthrough nativo</text>
        <rect class="node" x="8" y="230" width="212" height="46" rx="6"/>
        <text class="t-label" x="22" y="250">POST /v1/messages</text>
        <text class="t-dim" x="22" y="266">Anthropic · messages</text>
        <rect class="node-accent" x="316" y="122" width="128" height="46" rx="6"/>
        <text class="t-accent" x="334" y="142">proxy</text>
        <text class="t-dim" x="334" y="158">tradução + auth</text>
        <rect class="node-term" x="540" y="122" width="212" height="46" rx="6"/>
        <text class="t-term" x="556" y="142">Responses API</text>
        <text class="t-termdim" x="556" y="158">sua assinatura (Codex)</text>
        <path class="flow-line" d="M220 37 C 268 37, 268 145, 314 145"/>
        <path class="flow-line" d="M220 145 H 314"/>
        <path class="flow-line" d="M220 253 C 268 253, 268 145, 314 145"/>
        <path class="flow-line" d="M446 145 H 538"/>
      </svg>
    </div>

    <nav class="index rise" style="--d: 2">
      <a href="#como-funciona"><span class="n">01</span>Como funciona</a>
      <a href="#login-api-key"><span class="n">02</span>Login e API key</a>
      <a href="#rotacao"><span class="n">03</span>Rotação de API key</a>
      <a href="#endpoints"><span class="n">04</span>Endpoints</a>
      <a href="#traducao-responses"><span class="n">05</span>Tradução para a Responses API</a>
      <a href="#logout"><span class="n">06</span>Logout e exclusão de dados</a>
      <a href="#privacidade"><span class="n">07</span>Privacidade e retenção</a>
      <a href="#suporte"><span class="n">08</span>Suporte</a>
    </nav>

    <section class="panel rise" style="--d: 3" id="como-funciona">
      <p class="eyebrow"><span class="tick">///</span> 01</p>
      <h2>Como funciona</h2>
      <ol>
        <li><strong>Login OAuth (PKCE):</strong> cada usuário autoriza o proxy a agir em nome da própria conta ChatGPT em <code>/login</code>. Os tokens OAuth ficam guardados no banco <strong>cifrados em repouso</strong> (Fernet), vinculados ao usuário.</li>
        <li><strong>API key exibida uma única vez:</strong> ao concluir o login, uma key <code>sk-...</code> é gerada e mostrada na tela — guarde-a, pois ela não é exibida de novo.</li>
        <li><strong>Bearer key nas chamadas:</strong> os clientes enviam <code>Authorization: Bearer sk-...</code> nos endpoints <code>/v1/*</code>, como em qualquer API OpenAI/Anthropic.</li>
        <li><strong>Assinatura do próprio usuário upstream:</strong> o proxy resolve a key → usuário → credencial OAuth e chama o backend Codex com a assinatura daquela pessoa, com <strong>refresh automático</strong> do access token (5 minutos antes da expiração).</li>
      </ol>
    </section>

    <section class="panel rise" style="--d: 4" id="login-api-key">
      <p class="eyebrow"><span class="tick">///</span> 02</p>
      <h2>Login e API key</h2>
      <ol>
        <li>Abra <a href="/login">/login</a> e clique em <strong>Iniciar login com ChatGPT</strong>.</li>
        <li>Autorize o acesso na página do ChatGPT.</li>
        <li>Quando o navegador falhar ao abrir <code>http://localhost:1455/auth/callback?code=...</code> (<strong>normal em Docker/remoto</strong>), não feche a aba: copie a <strong>URL completa da barra de endereços</strong>.</li>
        <li>Cole a URL no campo indicado e clique em <strong>Concluir login</strong>.</li>
        <li>Copie a API key <code>sk-...</code> exibida — ela aparece <strong>apenas desta vez</strong>.</li>
      </ol>
    </section>

    <section class="panel rise" style="--d: 5" id="rotacao">
      <p class="eyebrow"><span class="tick">///</span> 03</p>
      <h2>Rotação de API key</h2>
      <p>
        Para recuperar acesso quando a key vaza ou se perde, basta fazer
        <a href="/login">login novamente em /login</a>: um re-login na mesma conta
        (identificada pelo <code>account_id</code>) <strong>revoga todas as API keys
        antigas</strong> e emite uma nova. Re-login nunca duplica usuário.
      </p>
    </section>

    <section class="panel rise" style="--d: 6" id="endpoints">
      <p class="eyebrow"><span class="tick">///</span> 04</p>
      <h2>Endpoints</h2>
      <p>Base URL: <code>https://chatgpt-openai-proxy.fastapicloud.dev</code> — substitua <code>$KEY</code> pela sua API key.</p>

      <p><strong>Chat Completions (OpenAI):</strong></p>
      <pre><code>curl https://chatgpt-openai-proxy.fastapicloud.dev/v1/chat/completions \\
  -H "Authorization: Bearer $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "Olá!"}]}'</code></pre>

      <p><strong>Responses API (OpenAI):</strong></p>
      <pre><code>curl https://chatgpt-openai-proxy.fastapicloud.dev/v1/responses \\
  -H "Authorization: Bearer $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "gpt-6.1-sol", "input": "Olá!"}'</code></pre>

      <p><strong>Messages (Anthropic):</strong></p>
      <pre><code>curl https://chatgpt-openai-proxy.fastapicloud.dev/v1/messages \\
  -H "Authorization: Bearer $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "gpt-6.1-sol", "max_tokens": 1024, "messages": [{"role": "user", "content": "Olá!"}]}'</code></pre>

      <p><strong>Listagem de modelos:</strong></p>
      <pre><code>curl https://chatgpt-openai-proxy.fastapicloud.dev/v1/models -H "Authorization: Bearer $KEY"</code></pre>

      <p><strong>Saúde (público):</strong></p>
      <pre><code>curl https://chatgpt-openai-proxy.fastapicloud.dev/health</code></pre>
    </section>

    <section class="panel rise" style="--d: 7" id="traducao-responses">
      <p class="eyebrow"><span class="tick">///</span> 05</p>
      <h2>Tradução para a Responses API</h2>
      <p>
        O backend do Codex fala <strong>apenas a Responses API</strong>. Quem já fala
        Responses API usa <code>POST /v1/responses</code> com passthrough direto; para
        os outros formatos, o proxy traduz Chat Completions e Anthropic Messages —
        regras aplicadas em <code>chat_to_responses</code>:
      </p>
      <ul>
        <li>Sempre envia <code>store: false</code> ao backend.</li>
        <li>Mensagens <code>system</code>/<code>developer</code> viram <code>instructions</code>, concatenadas com uma linha em branco; sem nenhuma delas, usa-se o fallback <code>"You are a helpful assistant."</code> (o backend rejeita <code>instructions</code> vazio).</li>
        <li><code>tools[].function</code> é achatado para <code>{name, description, parameters}</code> no formato da Responses API.</li>
        <li>Mensagens com <code>role: "tool"</code> viram itens <code>function_call_output</code> (com <code>call_id</code>).</li>
        <li>Nos clientes Anthropic, <code>max_tokens</code> vira <code>max_completion_tokens</code> internamente — mas <strong>nenhum limite de tokens chega ao backend</strong>: o plano rejeita <code>max_output_tokens</code> ("Unsupported parameter").</li>
        <li><code>reasoning_effort</code> (string) e <code>reasoning.effort</code> (objeto) são repassados como <code>reasoning.effort</code>. Sem esse repasse, o backend trata reasoning como ativo e rejeita <code>temperature != 1</code>; com effort <code>none</code> o inverso vale — o backend rejeita qualquer <code>temperature</code>, então o campo é removido.</li>
        <li>Streams de chat terminam com <code>data: [DONE]</code>; streams Anthropic usam eventos SSE (<code>message_start</code>, <code>content_block_*</code>, <code>message_delta</code>, <code>message_stop</code>).</li>
        <li>O proxy só fala com modelos do ChatGPT Plan. Se o cliente pedir um nome fora da allowlist (SDKs Anthropic costumam mandar <code>claude-*</code>), o upstream usa <code>DEFAULT_MODEL</code> (<code>gpt-6.1-sol</code> por padrão) e a resposta ecoa o nome que o cliente pediu.</li>
      </ul>
    </section>

    <section class="panel rise" style="--d: 8" id="logout">
      <p class="eyebrow"><span class="tick">///</span> 06</p>
      <h2>Logout e exclusão de dados</h2>
      <p>
        O <code>/logout</code> remove permanentemente tudo o que o proxy guarda sobre
        você — como se nunca tivesse sido cadastrado:
      </p>
      <ul>
        <li><code>GET /logout</code> mostra uma página para colar a API key e segurar o botão para confirmar a exclusão.</li>
        <li><code>POST /logout</code> com <code>Authorization: Bearer &lt;key&gt;</code> deleta o usuário, as credenciais OAuth e <strong>TODAS</strong> as API keys dele do banco, em uma única operação.</li>
        <li>A API key para de funcionar <strong>na hora</strong> (passa a retornar 401).</li>
        <li>A exclusão é <strong>irreversível</strong> — não há como desfazer.</li>
        <li>Para voltar a usar o proxy, basta fazer <a href="/login">/login</a> de novo (será criado um novo usuário com uma nova key).</li>
      </ul>
      <p><strong>Exemplo:</strong></p>
      <pre><code>curl -X POST https://chatgpt-openai-proxy.fastapicloud.dev/logout \\
  -H "Authorization: Bearer $KEY"</code></pre>
    </section>

    <section class="panel rise" style="--d: 9" id="privacidade">
      <p class="eyebrow"><span class="tick">///</span> 07</p>
      <h2>Privacidade e retenção</h2>
      <p><strong>O que o proxy guarda no banco:</strong></p>
      <ul>
        <li>Nome de usuário e <code>account_id</code> da conta ChatGPT (identidade estável usada no re-login).</li>
        <li>Tokens OAuth (<code>access_token</code>/<code>refresh_token</code>) <strong>cifrados em repouso</strong> com Fernet — no banco só existe ciphertext.</li>
        <li>API keys <strong>apenas como hash SHA-256</strong> — a chave completa nunca é armazenada.</li>
        <li>Metadados: labels de keys, timestamps de criação, último login e último uso de cada key.</li>
      </ul>
      <p><strong>O que o proxy NÃO guarda:</strong></p>
      <ul>
        <li><strong>Conteúdo das conversas.</strong> Prompts e respostas passam pelo proxy sem serem persistidos; os logs operacionais não incluem payloads.</li>
        <li>Toda chamada ao backend Codex vai com <code>store: false</code>, para que o upstream também não retenha o histórico pela API.</li>
      </ul>
      <p><strong>Retenção:</strong></p>
      <ul>
        <li>Os dados ficam no banco <strong>enquanto a conta existir</strong> — não há expiração automática.</li>
        <li>A exclusão é imediata, completa e irreversível via <a href="/logout">/logout</a> (self-service) ou pelo operador do serviço.</li>
        <li>Em caso de vazamento do banco, tokens e keys são inúteis: os tokens exigem a chave Fernet (que fica fora do banco, em env/keyfile) e as keys só existem como hash irreversível.</li>
      </ul>
      <p>
        <strong>Hospedagem:</strong> o deploy de produção roda no
        <a href="https://fastapicloud.com" target="_blank" rel="noopener">FastAPI Cloud</a>
        e o banco de dados é o <a href="https://neon.tech" target="_blank" rel="noopener">Neon</a>
        (Postgres gerenciado, integração nativa da plataforma) — infraestrutura, logs de
        plataforma e o armazenamento seguem as políticas deles. Detalhes na
        <a href="https://fastapicloud.com/legal/privacy-policy/" target="_blank" rel="noopener">política de privacidade do FastAPI Cloud</a>
        e no
        <a href="https://neon.tech/privacy-policy" target="_blank" rel="noopener">privacy notice do Neon (Databricks)</a>.
      </p>
    </section>

    <section class="panel rise" style="--d: 10" id="suporte">
      <p class="eyebrow"><span class="tick">///</span> 08</p>
      <h2>Suporte</h2>
      <p>
        Encontrou um bug, tem dúvida de uso ou quer pedir uma feature? Abra uma
        <strong>issue no GitHub</strong>:
      </p>
      <p>
        <a class="btn" href="https://github.com/lucasliet/chatgpt-openai-proxy/issues" target="_blank" rel="noopener">Abrir issue ↗</a>
      </p>
      <p>
        Ao reportar, inclua o endpoint chamado, o status HTTP recebido e o corpo do erro
        (nunca a sua API key nem tokens). Antes de abrir issue, vale checar o
        <a href="/health">/health</a> e refazer o <a href="/login">/login</a> se a key estiver
        respondendo 401.
      </p>
    </section>

    <footer class="footer">
      <span>chatgpt-openai-proxy · FastAPI</span>
      <span><a href="/health">/health</a> · <a href="/login">/login</a> · <a href="/logout">/logout</a> · <a href="https://github.com/lucasliet/chatgpt-openai-proxy/issues" target="_blank" rel="noopener">suporte</a></span>
    </footer>
  </div>
  """
        + THEME_TOGGLE_SCRIPT
        + """</body>
</html>"""
    )
