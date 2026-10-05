"""Landing page e documentação de uso — ``GET /``.

Renderiza uma página HTML self-contained que documenta o proxy: como funciona
o login OAuth, como usar a API key nas chamadas OpenAI/Anthropic, as regras
de tradução para a Responses API do Codex e o fluxo de logout/exclusão de
dados. O CSS base vem de ``app/routers/theme.py`` (design system compartilhado
com /login e /logout); aqui ficam só os estilos específicos (hero, diagrama
de tradução e índice).
"""

import html
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from .theme import (
    BASE_CSS,
    FAVICON_SVG,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
    favicon_link,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    root_path = request.scope.get("root_path", "").rstrip("/")
    base_url = request.base_url.replace(path=root_path)
    return _render_home_html(str(base_url).rstrip("/"), root_path)


@router.get("/favicon.svg", include_in_schema=False)
@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(
        FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


_OG_COVER_PATH = Path(__file__).resolve().parent.parent / "assets" / "og-cover.png"


@router.get("/og-cover.png", include_in_schema=False)
async def og_cover():
    return FileResponse(
        _OG_COVER_PATH,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


_PAGE_CSS = """
.topbar { flex-wrap: wrap; }
.topbar nav { flex-wrap: wrap; }
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
.diagram.is-offscreen .flow-line { animation-play-state: paused; }

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
@media (hover: hover) and (pointer: fine) {
  .index a:hover { color: var(--link); }
}
.index .n { color: var(--link); margin-right: 0.35em; }

section[id] { scroll-margin-top: 1.5rem; }
.panel ol, .panel ul { margin: 0.5rem 0; padding-left: 1.4rem; }
.panel li { margin: 0.3rem 0; }
.panel p { margin: 0.5rem 0; }
"""


def _render_home_html(base_url: str, root_path: str = "") -> str:
    return (
        """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChatGPT Proxy — Docs</title>
  <meta name="description" content="Autentique sua conta ChatGPT via OAuth, receba uma API key e use a sua assinatura em clientes compatíveis com Responses API, Chat Completions ou Anthropic Messages.">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="chatgpt-openai-proxy">
  <meta property="og:locale" content="pt_BR">
  <meta property="og:title" content="ChatGPT Proxy — Docs">
  <meta property="og:description" content="Autentique sua conta ChatGPT via OAuth, receba uma API key e use a sua assinatura em clientes compatíveis com Responses API, Chat Completions ou Anthropic Messages.">
  <meta property="og:url" content="__PROXY_BASE_URL__/">
  <meta property="og:image" content="__PROXY_BASE_URL__/og-cover.png">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="640">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:image" content="__PROXY_BASE_URL__/og-cover.png">
  <meta name="twitter:title" content="ChatGPT Proxy — Docs">
  <meta name="twitter:description" content="Autentique sua conta ChatGPT via OAuth, receba uma API key e use a sua assinatura em clientes compatíveis com Responses API, Chat Completions ou Anthropic Messages.">
  """
        + favicon_link(html.escape(root_path, quote=True))
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
        <a href="/dashboard">/dashboard</a>
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
        assinatura</strong> em clientes compatíveis com Responses API,
        Chat Completions ou Anthropic Messages. O proxy adapta as chamadas
        para o backend Codex.
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
        <li><strong>Conexão com o ChatGPT:</strong> o login OAuth (PKCE) autoriza o acesso à sua conta e gera uma API key do proxy.</li>
        <li><strong>Autenticação das chamadas:</strong> envie <code>Authorization: Bearer sk-...</code> nos endpoints <code>/v1/*</code>.</li>
        <li><strong>Uso da sua assinatura:</strong> a chave identifica sua conta, e as chamadas ao Codex usam suas credenciais OAuth. O proxy renova o token de acesso automaticamente quando necessário.</li>
      </ol>
    </section>

    <section class="panel rise" style="--d: 4" id="login-api-key">
      <p class="eyebrow"><span class="tick">///</span> 02</p>
      <h2>Login e API key</h2>
      <ol>
        <li>Abra <a href="/login">/login</a> e clique em <strong>Iniciar login com ChatGPT</strong>.</li>
        <li>Autorize o acesso na página do ChatGPT.</li>
        <li>Após a autorização, copie a <strong>URL completa da barra de endereços</strong>, iniciada por <code>http://localhost:1455/auth/callback?code=...</code>. Se a página não abrir, isso é esperado neste fluxo: o que importa é a URL.</li>
        <li>Cole a URL no campo indicado e clique em <strong>Concluir login</strong>.</li>
        <li>Copie a API key <code>sk-...</code> exibida — ela aparece <strong>apenas desta vez</strong>.</li>
      </ol>
    </section>

    <section class="panel rise" style="--d: 5" id="rotacao">
      <p class="eyebrow"><span class="tick">///</span> 03</p>
      <h2>Rotação de API key</h2>
      <p>
        Se perder sua chave ou suspeitar de vazamento, faça
        <a href="/login">login novamente</a> com a mesma conta ChatGPT.
        Isso <strong>revoga todas as API keys anteriores</strong> e gera uma nova,
        sem duplicar sua conta no proxy. Atualize a chave nos seus clientes.
      </p>
    </section>

    <section class="panel rise" style="--d: 6" id="endpoints">
      <p class="eyebrow"><span class="tick">///</span> 04</p>
      <h2>Endpoints</h2>
      <p>Base URL: <code>__PROXY_BASE_URL__</code> — substitua <code>$KEY</code> pela sua API key.</p>

      <p><strong>Chat Completions (OpenAI):</strong></p>
      <pre><code>curl __PROXY_BASE_URL__/v1/chat/completions \\
  -H "Authorization: Bearer $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "gpt-6.1-sol", "messages": [{"role": "user", "content": "Olá!"}]}'</code></pre>

      <p><strong>Responses API (OpenAI):</strong></p>
      <pre><code>curl __PROXY_BASE_URL__/v1/responses \\
  -H "Authorization: Bearer $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "gpt-6.1-sol", "input": "Olá!"}'</code></pre>

      <p><strong>Messages (Anthropic):</strong></p>
      <pre><code>curl __PROXY_BASE_URL__/v1/messages \\
  -H "Authorization: Bearer $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "gpt-6.1-sol", "max_tokens": 1024, "messages": [{"role": "user", "content": "Olá!"}]}'</code></pre>

      <p><strong>Listagem de modelos:</strong></p>
      <pre><code>curl __PROXY_BASE_URL__/v1/models -H "Authorization: Bearer $KEY"</code></pre>

      <p><strong>Saúde (público):</strong></p>
      <pre><code>curl __PROXY_BASE_URL__/health</code></pre>

      <p><strong>Limites da assinatura Codex:</strong> percentuais usados, renovação das janelas e créditos quando disponíveis. Incluem uso fora do proxy; não são um histórico de tokens ou custos.</p>
      <pre><code>curl __PROXY_BASE_URL__/v1/usage -H "Authorization: Bearer $KEY"</code></pre>
    </section>

    <section class="panel rise" style="--d: 7" id="traducao-responses">
      <p class="eyebrow"><span class="tick">///</span> 05</p>
      <h2>Tradução para a Responses API</h2>
      <p>
        O backend do Codex fala <strong>apenas a Responses API</strong>. Quem já fala
        Responses API usa <code>POST /v1/responses</code>; os demais formatos são
        convertidos antes do envio. Principais regras de compatibilidade:
      </p>
      <ul>
        <li>As chamadas convertidas usam <code>store: false</code>, exigido pelo backend Codex.</li>
        <li>Mensagens <code>system</code>/<code>developer</code> viram <code>instructions</code>, concatenadas com uma linha em branco; sem nenhuma delas, usa-se o fallback <code>"You are a helpful assistant."</code> (o backend rejeita <code>instructions</code> vazio).</li>
        <li><code>tools[].function</code> é achatado para <code>{name, description, parameters}</code> no formato da Responses API.</li>
        <li>Mensagens com <code>role: "tool"</code> viram itens <code>function_call_output</code> (com <code>call_id</code>).</li>
        <li>Nos clientes Anthropic, <code>max_tokens</code> vira <code>max_completion_tokens</code> internamente — mas <strong>nenhum limite de tokens chega ao backend</strong>: o plano rejeita <code>max_output_tokens</code> ("Unsupported parameter").</li>
        <li><code>reasoning_effort</code> (string) e <code>reasoning.effort</code> (objeto) são repassados como <code>reasoning.effort</code>. Sem esse repasse, o backend trata reasoning como ativo e rejeita <code>temperature != 1</code>; com effort <code>none</code> o inverso vale — o backend rejeita qualquer <code>temperature</code>, então o campo é removido.</li>
        <li>Streams de chat terminam com <code>data: [DONE]</code>; streams Anthropic usam eventos SSE (<code>message_start</code>, <code>content_block_*</code>, <code>message_delta</code>, <code>message_stop</code>).</li>
        <li>O <code>model</code> é repassado ao Codex em todos os endpoints (incluindo Anthropic Messages). Use um modelo do ChatGPT Plan — nomes <code>claude-*</code> não são traduzidos.</li>
      </ul>
    </section>

    <section class="panel rise" style="--d: 8" id="logout">
      <p class="eyebrow"><span class="tick">///</span> 06</p>
      <h2>Logout e exclusão de dados</h2>
      <p>
        Apesar do nome, <code>/logout</code> <strong>exclui sua conta</strong>, não apenas
        encerra uma sessão. A exclusão do banco ativo é imediata e irreversível.
      </p>
      <ul>
        <li><code>GET /logout</code> mostra uma página para colar a API key e segurar o botão para confirmar a exclusão.</li>
        <li><code>POST /logout</code> com <code>Authorization: Bearer &lt;key&gt;</code> remove o cadastro, as credenciais OAuth, todas as API keys e a telemetria em uma única transação.</li>
        <li>As chaves deixam de funcionar (HTTP 401), e as sessões do dashboard perdem validade.</li>
        <li>Para voltar a usar o proxy, faça <a href="/login">login novamente</a>. Será criada uma nova conta no proxy, com uma nova chave.</li>
      </ul>
      <p><strong>Exemplo:</strong></p>
      <pre><code>curl -X POST __PROXY_BASE_URL__/logout \\
  -H "Authorization: Bearer $KEY"</code></pre>
    </section>

    <section class="panel rise" style="--d: 9" id="privacidade">
      <p class="eyebrow"><span class="tick">///</span> 07</p>
      <h2>Privacidade e retenção</h2>
      <p><strong>O que o proxy guarda no banco:</strong></p>
      <ul>
        <li>Nome de usuário e <code>account_id</code> da conta ChatGPT (identidade estável usada no re-login).</li>
        <li>Tokens OAuth (<code>access_token</code>/<code>refresh_token</code>) <strong>cifrados em repouso</strong> com Fernet.</li>
        <li>API keys <strong>apenas como hash SHA-256</strong> — a chave completa nunca é armazenada.</li>
        <li>Metadados: rótulos das chaves, datas de criação, último login e último uso de cada chave.</li>
        <li><strong>Telemetria de uso:</strong> totais por usuário, hora UTC e modelo executado — chamadas concluídas, falhas e interrompidas; tokens de entrada, entrada em cache e saída; chamadas sem uso informado; e estimativas de custo em USD.</li>
      </ul>
      <p><strong>O que o proxy não guarda:</strong></p>
      <ul>
        <li><strong>Conteúdo das conversas:</strong> prompts, respostas e conteúdo de ferramentas passam pelo proxy sem serem persistidos. Os logs operacionais não incluem esses conteúdos.</li>
        <li><strong>Registros individuais de chamadas:</strong> a telemetria guarda apenas os totais descritos acima, sem IPs ou payloads.</li>
      </ul>
      <p><strong>Retenção:</strong></p>
      <ul>
        <li>Dados de cadastro, credenciais e API keys ficam no banco <strong>enquanto a conta existir</strong>.</li>
        <li>A telemetria fica disponível por <strong>até 30 dias</strong>. Agregados expirados são removidos na inicialização e a cada hora enquanto o serviço está ativo; se estiver desligado, a limpeza ocorre no próximo início.</li>
        <li>Para remover o cadastro e a telemetria antes disso, use <a href="#logout">/logout</a>, conforme descrito acima. Backups e logs de infraestrutura seguem as políticas da hospedagem.</li>
      </ul>
      <p><strong>Proteção das credenciais:</strong> a chave Fernet fica separada do banco, em variável de ambiente ou arquivo local protegido. As API keys são armazenadas como hash. Essas medidas reduzem o risco em caso de vazamento do banco, mas não substituem a proteção do servidor e de seus segredos.</p>
      <p><strong>Acesso e finalidade:</strong> a telemetria serve para acompanhar consumo e modelos utilizados. Cada usuário consulta somente os próprios dados em <a href="/dashboard">/dashboard</a>, informando sua API key do proxy. A sessão do dashboard expira em 12 horas e perde validade se a chave for revogada; sair dela não exclui a conta.</p>
      <p><strong>Estimativa de custo:</strong> usamos os preços públicos da API OpenAI via models.dev, considerando entrada, cache, saída e faixas de contexto. É uma referência equivalente de API, <strong>não uma cobrança da assinatura ChatGPT</strong>. Modelos sem preço ou chamadas sem uso informado ficam sem estimativa; totais podem ser parciais. Atualizações de preço não recalculam o histórico. O catálogo público é consultado pelo servidor sem enviar dados de usuários ou conversas ao models.dev.</p>
      <p><strong>Limites da assinatura:</strong> consultamos a conta Codex com suas credenciais OAuth e mostramos apenas dados de limites, créditos e disponibilidade de modelos, sem email ou identificadores da conta. Esses dados ficam em cache temporário de até 60 segundos por instância, sem histórico no banco. A consulta usa um endpoint interno do ChatGPT e pode ficar indisponível sem afetar a telemetria local.</p>
      <p>
        <strong>Hospedagem:</strong> o deploy público deste projeto utiliza o
        <a href="https://fastapicloud.com" target="_blank" rel="noopener">FastAPI Cloud</a>
        e o <a href="https://neon.tech" target="_blank" rel="noopener">Neon</a> como banco de dados
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
        Encontrou um problema, tem uma dúvida ou quer sugerir uma melhoria? Abra uma
        <strong>issue no GitHub</strong>:
      </p>
      <p>
        <a class="btn" href="https://github.com/lucasliet/chatgpt-openai-proxy/issues" target="_blank" rel="noopener">Abrir issue ↗</a>
      </p>
      <p>
        Informe o endpoint, o status HTTP e a mensagem de erro, removendo chaves,
        tokens e conteúdo de conversas. Verifique <a href="/health">/health</a> para
        confirmar que o serviço está disponível. Se sua chave retornar HTTP 401,
        consulte as orientações de <a href="#rotacao">rotação de API key</a>.
      </p>
    </section>

    <footer class="footer">
      <span>chatgpt-openai-proxy · FastAPI</span>
      <span><a href="/health">/health</a> · <a href="/login">/login</a> · <a href="/logout">/logout</a> · <a href="https://github.com/lucasliet/chatgpt-openai-proxy/issues" target="_blank" rel="noopener">suporte</a></span>
    </footer>
  </div>
  <script>
    (function pauseDiagramOffscreen() {
      const diagram = document.querySelector('.diagram');
      if (!diagram || !('IntersectionObserver' in window)) return;
      new IntersectionObserver(function (entries) {
        diagram.classList.toggle('is-offscreen', !entries[0].isIntersecting);
      }).observe(diagram);
    })();
  </script>
  """
        + THEME_TOGGLE_SCRIPT
        + """</body>
</html>"""
    ).replace("__PROXY_BASE_URL__", html.escape(base_url, quote=True))
