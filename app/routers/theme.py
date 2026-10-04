"""Design system compartilhado das páginas web do proxy (``/``, ``/login``, ``/logout``).

As três páginas são HTML self-contained renderizado pelo próprio router; o
CSS base (tokens, tipografia, componentes, motion) vive aqui para não ser
duplicado. Cada página concatena ``BASE_CSS`` com o seu CSS específico.

Direção visual: "esquema técnico" — papel claro frio com grade sutil,
hairlines, anotações em IBM Plex Mono e blocos de terminal escuros para
código. Movimento é deliberadamente escasso: o fluxo tracejado do diagrama
(hero), uma entrada única por página e micro-feedback de pressão; tudo
coberto por ``prefers-reduced-motion``.
"""

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;700&display=swap');

:root {
  --paper: #e9edf1;
  --grid: rgba(90, 110, 130, 0.07);
  --surface: #f7f9fa;
  --ink: #1a2027;
  --muted: #55606c;
  --line: #c7d0d9;
  --accent: #2b3fe0;
  --accent-ink: #1e2fb0;
  --link: #2b3fe0;
  --link-hover: #1e2fb0;
  --term-bg: #10151c;
  --term-ink: #d9e2ec;
  --term-dim: #6b7885;
  --term-accent: #8fa8ff;
  --danger: #c0392b;
  --danger-ink: #96271b;
  --ok-bg: #e0f0e4;
  --ok-ink: #1e6b34;
  --err-bg: #f7e3e0;
  --err-ink: #a03024;
  --font-sans: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace;
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --dur-page-enter: 380ms;
  --dur-reveal: 240ms;
  --radius: 6px;
  color-scheme: light;
}

[data-theme="dark"] {
  --paper: #10151c;
  --grid: rgba(140, 160, 190, 0.06);
  --surface: #171e28;
  --ink: #dde5ee;
  --muted: #8b96a3;
  --line: #2a3442;
  --link: #8fa8ff;
  --link-hover: #b9c6ff;
  --term-bg: #0b0f14;
  --ok-bg: #12281a;
  --ok-ink: #6fce85;
  --err-bg: #2b1512;
  --err-ink: #e88a7d;
  color-scheme: dark;
}

* { box-sizing: border-box; }

html { scroll-behavior: smooth; }

body {
  margin: 0;
  background: var(--paper);
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 32px 32px;
  color: var(--ink);
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 1.6;
  transition: background-color 250ms ease-out, color 250ms ease-out;
}

.container { max-width: 880px; margin: 0 auto; padding: 0 1.25rem 4rem; }
.container.narrow { max-width: 620px; }

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
  padding: 1.1rem 0;
  margin-bottom: 2rem;
  border-bottom: 1px solid var(--line);
  font-family: var(--font-mono);
  font-size: 0.8rem;
}
.topbar .brand { color: var(--ink); text-decoration: none; font-weight: 500; letter-spacing: 0.04em; white-space: nowrap; }
.topbar nav { display: flex; align-items: center; }
.topbar nav a { color: var(--muted); text-decoration: none; margin-left: 1.1rem; transition: color 150ms ease-out; }
@media (hover: hover) and (pointer: fine) {
  .topbar nav a:hover { color: var(--link); }
}

a { color: var(--link); text-decoration-thickness: 1px; text-underline-offset: 3px; transition: color 150ms ease-out; }
@media (hover: hover) and (pointer: fine) {
  a:hover { color: var(--link-hover); }
}

h1, h2, h3 { line-height: 1.15; letter-spacing: -0.01em; }

.muted { color: var(--muted); }

code {
  font-family: var(--font-mono);
  font-size: 0.85em;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0.1em 0.35em;
}

pre {
  background: var(--term-bg);
  color: var(--term-ink);
  border-radius: var(--radius);
  padding: 1rem 1.1rem;
  overflow-x: auto;
  font-size: 0.82rem;
  line-height: 1.55;
}
pre code { background: none; border: none; padding: 0; color: inherit; font-size: inherit; }

.eyebrow {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 0.6rem;
}
.eyebrow .tick { color: var(--link); }

.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 1.4rem 1.5rem;
  margin: 1rem 0;
}
.panel h2 { margin-top: 0; }

.btn {
  display: inline-block;
  font-family: var(--font-sans);
  font-weight: 500;
  font-size: 0.95rem;
  padding: 0.65rem 1.15rem;
  border-radius: var(--radius);
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  text-decoration: none;
  transition: background 150ms ease-out, border-color 150ms ease-out, color 150ms ease-out, transform 120ms ease-out;
}
@media (hover: hover) and (pointer: fine) {
  .btn:hover { background: var(--accent-ink); border-color: var(--accent-ink); color: #fff; }
}
.btn:active { transform: scale(0.98); }
.btn.ghost { background: transparent; color: var(--ink); border-color: var(--line); }
@media (hover: hover) and (pointer: fine) {
  .btn.ghost:hover { background: transparent; border-color: var(--ink); color: var(--ink); }
}
.btn.danger { background: var(--danger); border-color: var(--danger); }
@media (hover: hover) and (pointer: fine) {
  .btn.danger:hover { background: var(--danger-ink); border-color: var(--danger-ink); }
}
.btn:disabled { opacity: 0.55; cursor: not-allowed; }

input[type="text"], input[type="password"] {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--ink);
  border-radius: var(--radius);
  padding: 0.7rem 0.8rem;
  font-family: var(--font-mono);
  font-size: 0.88rem;
  transition: border-color 150ms ease-out, box-shadow 150ms ease-out;
}
input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(43, 63, 224, 0.15); }

label { display: block; margin-bottom: 0.4rem; font-size: 0.85rem; color: var(--muted); }

.hidden { display: none; }

.keybox {
  margin-top: 1rem;
  padding: 1rem 1.1rem;
  background: var(--term-bg);
  color: var(--term-accent);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: 0.95rem;
  word-break: break-all;
}

.status { margin-top: 1rem; padding: 0.75rem 0.9rem; border-radius: var(--radius); font-size: 0.9rem; border: 1px solid transparent; }
.status.ok { background: var(--ok-bg); color: var(--ok-ink); border-color: var(--ok-ink); }
.status.err { background: var(--err-bg); color: var(--err-ink); border-color: var(--err-ink); }

.footer {
  margin-top: 3rem;
  padding-top: 1.2rem;
  border-top: 1px solid var(--line);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.footer a { color: var(--muted); }
@media (hover: hover) and (pointer: fine) {
  .footer a:hover { color: var(--link); }
}

:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

@keyframes rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
.rise { animation: rise var(--dur-page-enter) var(--ease-out) backwards; animation-delay: calc(var(--d, 0) * 60ms); }

.btn.hold {
  position: relative;
  overflow: hidden;
  user-select: none;
  touch-action: none;
}
.btn.hold .hold-fill {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.22);
  clip-path: inset(0 100% 0 0);
  transition: clip-path 200ms var(--ease-out);
  pointer-events: none;
}
.btn.hold.holding .hold-fill {
  clip-path: inset(0 0 0 0);
  transition: clip-path 2s linear;
}
.btn.hold .hold-label { position: relative; z-index: 1; }

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition-duration: 120ms !important; }
  .rise, .step, .keybox, .status:not(.hidden) {
    animation-name: fade-in !important;
    animation-duration: 120ms !important;
    animation-delay: 0ms !important;
  }
  .flow-line { animation: none !important; }
  .btn.hold .hold-fill {
    clip-path: inset(0 0 0 0);
    opacity: 0;
    transition: opacity 200ms var(--ease-out) !important;
  }
  .btn.hold.holding .hold-fill {
    opacity: 1;
    transition: opacity 2s linear !important;
  }
}
"""


# --- Seletor de tema (light/dark) -------------------------------------------
# O estado vive em <html data-theme>; o CSS abaixo dirige toda a animação e o
# JS só troca o atributo e persiste em localStorage. THEME_HEAD_SCRIPT vai no
# <head> ANTES do <style> para aplicar o tema salvo sem flash.

THEME_HEAD_SCRIPT = """<script>
  try {
    document.documentElement.dataset.theme =
      localStorage.getItem('theme') ||
      (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  } catch (e) {
    document.documentElement.dataset.theme = 'light';
  }
</script>
"""

THEME_TOGGLE_CSS = """
.theme-toggle {
  background: none;
  border: none;
  padding: 0;
  margin-left: 1.1rem;
  cursor: pointer;
  display: inline-flex;
}
.theme-toggle .track {
  display: block;
  width: 50px;
  height: 26px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--line);
  position: relative;
  transition: background 250ms ease-out, border-color 250ms ease-out, transform 120ms ease-out;
}
.theme-toggle:active .track { transform: scale(0.97); }
.theme-toggle .thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  display: grid;
  place-items: center;
  transition: transform 250ms var(--ease-out), background 250ms ease-out;
}
[data-theme="dark"] .theme-toggle .thumb { transform: translateX(24px); }
.theme-toggle svg {
  grid-area: 1 / 1;
  width: 13px;
  height: 13px;
  transition: opacity 200ms ease-out, transform 250ms var(--ease-out);
}
.theme-toggle .icon-sun { opacity: 1; }
.theme-toggle .icon-moon { opacity: 0; transform: rotate(-120deg) scale(0.4); }
[data-theme="dark"] .theme-toggle .icon-sun { opacity: 0; transform: rotate(120deg) scale(0.4); }
[data-theme="dark"] .theme-toggle .icon-moon { opacity: 1; transform: none; }
"""

THEME_TOGGLE_HTML = """<button class="theme-toggle" id="themeToggle" aria-label="Alternar entre tema claro e escuro" title="Alternar tema">
        <span class="track"><span class="thumb">
          <svg class="icon-sun" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="4" stroke="none"/><path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" fill="none"/></svg>
          <svg class="icon-moon" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
        </span></span>
      </button>"""

THEME_TOGGLE_SCRIPT = """<script>
  (function () {
    var toggle = document.getElementById('themeToggle');
    toggle.setAttribute('aria-pressed', document.documentElement.dataset.theme === 'dark');
    toggle.addEventListener('click', function () {
      var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      toggle.setAttribute('aria-pressed', next === 'dark');
      try { localStorage.setItem('theme', next); } catch (e) {}
    });
  })();
</script>
"""

# --- Favicon ------------------------------------------------------------------
# Nó hexagonal de seis pétalas que remete à marca do ChatGPT (sem copiar o
# traçado, que é marca registrada): arcos de 196° entrelaçados a cada 60°,
# traço --term-ink sobre fundo --term-bg. Servido pela rota /favicon.svg em
# home.py; /favicon.ico responde o mesmo SVG para os browsers que o pedem
# direto.

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#10151c"/>
  <g fill="none" stroke="#d9e2ec" stroke-width="4.6" stroke-linecap="round">
    <path d="M45.10 43.39 A11.5 11.5 0 1 1 45.10 20.61"/>
    <path d="M28.69 49.04 A11.5 11.5 0 1 1 48.41 37.65"/>
    <path d="M15.59 37.65 A11.5 11.5 0 1 1 35.31 49.04"/>
    <path d="M18.90 20.61 A11.5 11.5 0 1 1 18.90 43.39"/>
    <path d="M35.31 14.96 A11.5 11.5 0 1 1 15.59 26.35"/>
    <path d="M48.41 26.35 A11.5 11.5 0 1 1 28.69 14.96"/>
  </g>
</svg>
"""


def favicon_link(root_path: str = "") -> str:
    """Tag <link> do favicon; ``root_path`` deve vir já escapado para HTML."""
    return f'<link rel="icon" type="image/svg+xml" href="{root_path}/favicon.svg">'


HOLD_CONFIRM_SCRIPT = """<script>
  (function setupHoldConfirm() {
    const HOLD_MS = 2000;
    document.querySelectorAll('button[data-hold-confirm]').forEach(function (btn) {
      let timer = null;
      function cancel() {
        if (timer) { clearTimeout(timer); timer = null; }
        btn.classList.remove('holding');
      }
      function start(e) {
        if (btn.disabled || timer) return;
        if (e.type === 'pointerdown' && e.button !== 0) return;
        if (e.cancelable) e.preventDefault();
        btn.classList.add('holding');
        timer = setTimeout(function () {
          timer = null;
          btn.disabled = true;
          btn.form.submit();
        }, HOLD_MS);
      }
      btn.addEventListener('pointerdown', start);
      btn.addEventListener('pointerup', cancel);
      btn.addEventListener('pointerleave', cancel);
      btn.addEventListener('pointercancel', cancel);
      btn.addEventListener('keydown', function (e) {
        if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) start(e);
      });
      btn.addEventListener('keyup', function (e) {
        if (e.key === ' ' || e.key === 'Enter') cancel();
      });
      btn.addEventListener('blur', cancel);
    });
  })();
</script>
"""
