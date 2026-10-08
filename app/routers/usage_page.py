import html
import json
from datetime import datetime, timedelta
from decimal import Decimal
from enum import IntEnum
from typing import TypedDict

from sqlmodel import Session, select

from ..models import User, utcnow
from ..telemetry_models import PriceCatalog, UsageBucket
from .theme import (
    BASE_CSS,
    THEME_HEAD_SCRIPT,
    THEME_TOGGLE_CSS,
    THEME_TOGGLE_HTML,
    THEME_TOGGLE_SCRIPT,
    favicon_link,
)

USAGE_CSS = """
.topbar { flex-wrap:wrap; }
.usage-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; }
.stat { transition:border-color 150ms ease-out, transform 150ms ease-out; }
.stat .stat-label {
  margin:0 0 .4rem; font-family:var(--font-mono); font-size:.7rem;
  letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
}
.stat strong { display:block; font-family:var(--font-mono); font-size:clamp(1.15rem,3vw,1.7rem); overflow-wrap:anywhere; }
.stat .stat-sub { display:block; margin-top:.4rem; font-family:var(--font-mono); font-size:.74rem; color:var(--muted); }
.stat .stat-sub .ok { color:var(--ok-ink); }
.stat .stat-sub .err { color:var(--err-ink); }
@media (hover: hover) and (pointer: fine) {
  .stat:hover { border-color:var(--muted); transform:translateY(-2px); }
}
.usage-filters { display:flex; gap:.5rem; flex-wrap:wrap; margin:1.5rem 0; }
.usage-filters [aria-current] { background:var(--accent); border-color:var(--accent); color:#fff; }
.usage-filters[aria-busy="true"] { opacity:.55; pointer-events:none; }
.usage-filters [data-refresh] { margin-left:auto; background:rgba(90,110,130,.14); }
.usage-filters [data-refresh]:hover { background:rgba(90,110,130,.22); border-color:var(--ink); }
[data-theme="dark"] .usage-filters [data-refresh] { background:rgba(140,160,190,.16); }
[data-theme="dark"] .usage-filters [data-refresh]:hover { background:rgba(140,160,190,.26); }
.chart-wrap { position:relative; }
.usage-chart { width:100%; height:auto; display:block; touch-action:pan-y; }
.usage-chart text { fill:var(--muted); font-family:var(--font-mono); font-size:12px; }
.chart-crosshair { stroke:var(--muted); stroke-width:1; stroke-dasharray:3 3; }
.chart-dot { stroke:var(--surface); stroke-width:1.5; }
.chart-hit { cursor:crosshair; }
.chart-tooltip {
  position:absolute; top:0; left:0; z-index:2;
  transform:translate(-50%, calc(-100% - 12px));
  background:var(--term-bg); color:var(--term-ink);
  border:1px solid var(--line); border-radius:var(--radius);
  padding:.55rem .75rem; font-family:var(--font-mono); font-size:.72rem; line-height:1.55;
  white-space:nowrap; pointer-events:none; opacity:0;
  box-shadow:0 10px 28px rgba(0,0,0,.28);
  transition:opacity 120ms ease-out;
}
.chart-tooltip.below { transform:translate(-50%, 12px); }
.chart-tooltip.visible { opacity:1; }
.chart-tooltip .tt-time { display:block; color:var(--term-dim); margin-bottom:.2rem; }
.chart-tooltip .tt-row { display:flex; justify-content:space-between; gap:1.2rem; }
.chart-tooltip .tt-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:.45rem; }
.chart-tooltip .tt-total { border-top:1px solid var(--line); margin-top:.3rem; padding-top:.3rem; color:var(--term-accent); }
.usage-table-wrap { overflow-x:auto; }
.usage-table { width:100%; border-collapse:collapse; font-family:var(--font-mono); font-size:.8rem; }
.usage-table th,.usage-table td { text-align:right; padding:.6rem; border-bottom:1px solid var(--line); white-space:nowrap; }
.usage-table th:first-child,.usage-table td:first-child { text-align:left; }
.usage-legend { display:flex; flex-wrap:wrap; gap:.4rem 1.2rem; margin-top:.7rem; font-family:var(--font-mono); font-size:.78rem; }
.usage-legend span { display:inline-flex; align-items:center; gap:.45rem; }
.usage-legend i { display:inline-block; width:10px; height:10px; border-radius:3px; }
progress { width:100%; max-width:32rem; accent-color:var(--link); }
@media(max-width:600px) { .usage-summary { grid-template-columns:1fr; } }
@media (prefers-reduced-motion: reduce) {
  .chart-tooltip { transition:none !important; }
}
"""


class UsagePeriod(IntEnum):
    """Janelas de consulta aceitas em ``?days=`` (IntEnum converte a query string)."""

    TODAY = 1
    WEEK = 7
    MONTH = 30


class UsageTotals(TypedDict):
    calls: int
    completed: int
    failed: int
    interrupted: int
    unknown_usage: int
    unpriced: int
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    cost_usd: Decimal


def aggregate_usage(buckets: list[UsageBucket]) -> UsageTotals:
    fields = (
        "calls",
        "completed",
        "failed",
        "interrupted",
        "unknown_usage",
        "unpriced",
        "input_tokens",
        "cached_tokens",
        "output_tokens",
        "cost_usd",
    )
    return {
        field: sum(
            (getattr(bucket, field) for bucket in buckets),
            Decimal(0) if field == "cost_usd" else 0,
        )
        for field in fields
    }


CHART_WIDTH = 780
CHART_HEIGHT = 300
CHART_LEFT = 48
CHART_TOP = 16
CHART_PLOT_WIDTH = CHART_WIDTH - CHART_LEFT - 12
CHART_PLOT_HEIGHT = CHART_HEIGHT - CHART_TOP - 30
CHART_COLORS = ("var(--link)", "var(--ok-ink)", "var(--err-ink)", "var(--muted)")


def compact_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return str(value)


def nice_peak(value: int) -> int:
    """Menor teto "redondo" (1/2/2.5/5 × 10^n) acima do pico, para ticks legíveis."""
    if value <= 0:
        return 1
    magnitude = 10 ** (len(str(value)) - 1)
    for factor in (1, 2, 2.5, 5, 10):
        if value <= factor * magnitude:
            return int(factor * magnitude)
    return 10 * magnitude


CHART_INIT_SCRIPT = """<script>
  function initUsageChart() {
    var dataEl = document.getElementById('usage-chart-data');
    var svg = document.getElementById('usage-chart');
    if (!dataEl || !svg) return;
    var wrap = svg.closest('.chart-wrap');
    var data = JSON.parse(dataEl.textContent);
    var vb = svg.viewBox.baseVal;
    var crosshair = svg.querySelector('.chart-crosshair');
    var dotsLayer = svg.querySelector('.chart-dots');
    var paths = svg.querySelectorAll('polyline[data-series]');
    var NS = 'http://www.w3.org/2000/svg';
    var rootStyle = getComputedStyle(document.documentElement);
    var colors = [], dots = [];
    function resolveColor(el) {
      var stroke = getComputedStyle(el).stroke;
      var match = /^var\\((--[\\w-]+)\\)$/.exec(stroke);
      return match ? rootStyle.getPropertyValue(match[1]).trim() : stroke;
    }
    for (var i = 0; i < paths.length; i++) {
      colors.push(resolveColor(paths[i]));
      var dot = document.createElementNS(NS, 'circle');
      dot.setAttribute('r', '4');
      dot.setAttribute('class', 'chart-dot');
      dot.setAttribute('visibility', 'hidden');
      dotsLayer.appendChild(dot);
      dots.push(dot);
    }
    var tooltip = document.createElement('div');
    tooltip.className = 'chart-tooltip';
    wrap.appendChild(tooltip);
    var span = Math.max(data.hours - 1, 1);
    var ESCAPES = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
    function esc(s) { return s.replace(/[&<>"']/g, function (c) { return ESCAPES[c]; }); }
    function fmt(n) { return n.toLocaleString('pt-BR'); }
    function hide() {
      tooltip.classList.remove('visible');
      crosshair.setAttribute('visibility', 'hidden');
      dots.forEach(function (d) { d.setAttribute('visibility', 'hidden'); });
    }
    svg.addEventListener('pointermove', function (e) {
      var rect = svg.getBoundingClientRect();
      if (!rect.width) return;
      var vbX = (e.clientX - rect.left) * vb.width / rect.width;
      if (vbX < data.left || vbX > data.left + data.plotW) { hide(); return; }
      var idx = Math.round((vbX - data.left) / data.plotW * span);
      idx = Math.max(0, Math.min(data.hours - 1, idx));
      var x = data.left + idx * data.plotW / span;
      crosshair.setAttribute('x1', x);
      crosshair.setAttribute('x2', x);
      crosshair.setAttribute('visibility', 'visible');
      var topY = data.baseY, total = 0, rows = '';
      data.series.forEach(function (s, i) {
        var v = s.values[idx] || 0;
        total += v;
        var y = data.baseY - v * data.plotH / data.peak;
        dots[i].setAttribute('cx', x);
        dots[i].setAttribute('cy', y);
        dots[i].setAttribute('fill', colors[i]);
        dots[i].setAttribute('visibility', 'visible');
        if (v > 0 && y < topY) topY = y;
        rows += '<div class="tt-row"><span><i class="tt-dot" style="background:' +
          colors[i] + '"></i>' + esc(s.model) + '</span><span>' + fmt(v) + '</span></div>';
      });
      tooltip.innerHTML = '<span class="tt-time">' + esc(data.times[idx]) + '</span>' + rows +
        '<div class="tt-row tt-total"><span>Total</span><span>' + fmt(total) + ' tokens</span></div>';
      tooltip.classList.add('visible');
      var wrapRect = wrap.getBoundingClientRect();
      var pxX = rect.left - wrapRect.left + x * rect.width / vb.width;
      var pxY = rect.top - wrapRect.top + topY * rect.height / vb.height;
      var half = tooltip.offsetWidth / 2;
      tooltip.classList.toggle('below', pxY - tooltip.offsetHeight - 14 < 0);
      tooltip.style.left = Math.max(half + 4, Math.min(pxX, wrap.clientWidth - half - 4)) + 'px';
      tooltip.style.top = pxY + 'px';
    });
    svg.addEventListener('pointerleave', hide);
  }
  window.initUsageChart = initUsageChart;
  document.addEventListener('DOMContentLoaded', initUsageChart);
</script>"""


def usage_chart(buckets: list[UsageBucket], start: datetime, end: datetime) -> str:
    if not buckets:
        return '<p class="muted">Ainda não há chamadas de IA neste período.</p>'
    models = sorted({bucket.model for bucket in buckets})
    hours = int((end - start).total_seconds() // 3600) + 1
    values = {model: [0] * hours for model in models}
    for bucket in buckets:
        position = int((bucket.hour - start).total_seconds() // 3600)
        if 0 <= position < hours:
            values[bucket.model][position] += bucket.input_tokens + bucket.output_tokens
    peak = nice_peak(max(max(series) for series in values.values()))
    span = max(hours - 1, 1)
    base_y = CHART_TOP + CHART_PLOT_HEIGHT

    def x_of(index: float) -> float:
        return CHART_LEFT + index * CHART_PLOT_WIDTH / span

    def y_of(value: float) -> float:
        return base_y - value * CHART_PLOT_HEIGHT / peak

    grid, ticks = [], []
    for step in range(5):
        tick_value = peak * step // 4
        y = y_of(tick_value)
        grid.append(
            f'<path d="M{CHART_LEFT} {y:.1f}H{CHART_LEFT + CHART_PLOT_WIDTH}" stroke="var(--line)"/>'
        )
        ticks.append(
            f'<text x="{CHART_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{compact_tokens(tick_value)}</text>"
        )
    tick_indices = sorted({round(i * (hours - 1) / 5) for i in range(6)}) if hours > 1 else [0]
    for index in tick_indices:
        label = (start + timedelta(hours=index)).strftime("%d/%m %Hh")
        ticks.append(
            f'<text x="{x_of(index):.1f}" y="{CHART_HEIGHT - 8}" text-anchor="middle">{label}</text>'
        )
    series_markup, legend = [], []
    for index, model in enumerate(models):
        color = CHART_COLORS[index % len(CHART_COLORS)]
        series = values[model]
        line = " ".join(f"{x_of(hour):.1f},{y_of(value):.1f}" for hour, value in enumerate(series))
        area = (
            f'<polygon points="{x_of(0):.1f},{base_y} {line} {x_of(hours - 1):.1f},{base_y}" '
            f'fill="{color}" opacity="0.08"/>'
            if any(series)
            else ""
        )
        series_markup.append(
            f'{area}<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" data-series="{index}"/>'
        )
        legend.append(f'<span><i style="background:{color}"></i>{html.escape(model)}</span>')
    times = [
        (start + timedelta(hours=index)).strftime("%d/%m/%Y %H:%M UTC") for index in range(hours)
    ]
    payload = {
        "left": CHART_LEFT,
        "top": CHART_TOP,
        "plotW": CHART_PLOT_WIDTH,
        "plotH": CHART_PLOT_HEIGHT,
        "baseY": base_y,
        "peak": peak,
        "hours": hours,
        "times": times,
        "series": [{"model": model, "values": values[model]} for model in models],
    }
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return f"""<div class="chart-wrap">
    <svg id="usage-chart" class="usage-chart" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" aria-label="Tokens por hora UTC e modelo. Totais disponíveis na tabela abaixo. Passe o mouse para ver valores por hora.">
    {"".join(grid)}{"".join(ticks)}{"".join(series_markup)}
    <line class="chart-crosshair" y1="{CHART_TOP}" y2="{base_y}" visibility="hidden"/>
    <g class="chart-dots"></g>
    <rect class="chart-hit" x="{CHART_LEFT}" y="{CHART_TOP}" width="{CHART_PLOT_WIDTH}" height="{CHART_PLOT_HEIGHT}" fill="transparent"/>
    </svg>
    <script type="application/json" id="usage-chart-data">{data_json}</script>
    <div class="usage-legend">{"".join(legend)}</div>{CHART_INIT_SCRIPT}</div>"""


def format_cost(usage: UsageTotals) -> str:
    if usage["unpriced"] >= usage["calls"]:
        return "Indisponível"
    estimate = f"US$ {usage['cost_usd']:.6f}"
    return estimate + " (parcial)" if usage["unpriced"] else estimate


def model_rows(buckets: list[UsageBucket]) -> str:
    rows = []
    for model in sorted({bucket.model for bucket in buckets}):
        usage = aggregate_usage([bucket for bucket in buckets if bucket.model == model])
        rows.append(
            f"<tr><td>{html.escape(model)}</td><td>{usage['calls']:,}</td><td>{usage['input_tokens']:,}</td><td>{usage['cached_tokens']:,}</td><td>{usage['output_tokens']:,}</td><td>{format_cost(usage)}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="6">Nenhum consumo registrado.</td></tr>'


def render_period_content(
    session: Session,
    user: User,
    days: int,
    base: str,
    now: datetime | None = None,
) -> str:
    """Região da página que depende de ``?days=`` — reusada pela página e pelo partial."""
    now = now or utcnow()
    end = now.replace(minute=0, second=0, microsecond=0)
    start = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        if days == 1
        else end - timedelta(days=days) + timedelta(hours=1)
    )
    buckets = list(
        session.exec(
            select(UsageBucket)
            .where(
                UsageBucket.user_id == user.id,
                UsageBucket.hour >= start,
                UsageBucket.hour <= end,
            )
            .order_by(UsageBucket.hour)
        ).all()
    )
    totals = aggregate_usage(buckets)
    if totals["unpriced"] >= totals["calls"]:
        cost_main, cost_sub = "Indisponível", ""
    else:
        cost_main = f"US$ {totals['cost_usd']:.6f}"
        cost_sub = (
            '<span class="stat-sub">parcial — há chamadas sem estimativa</span>'
            if totals["unpriced"]
            else ""
        )
    filters = "".join(
        f'<a class="btn small ghost" data-days="{period}" href="{base}?days={period}" '
        f"{'aria-current=page' if days == period else ''}>{label}</a>"
        for period, label in ((1, "Hoje"), (7, "7 dias"), (30, "30 dias"))
    )
    refresh_button = (
        '<button type="button" class="btn small ghost" data-refresh '
        'aria-label="Atualizar os dados do período selecionado" '
        'title="Atualizar os dados (ignora o cache da página)">↻</button>'
    )
    unknown = (
        f"{totals['unknown_usage']} chamadas sem uso informado · {totals['unpriced']} sem estimativa. O custo exibido pode ser parcial."
        if totals["unpriced"]
        else "Todas as chamadas do período têm estimativa."
    )
    return f"""
      <div id="usage-content">
      <p class="muted">{start:%d/%m/%Y %H:%M} → {now:%d/%m/%Y %H:%M} UTC · retenção de 30 dias</p>
      <nav class="usage-filters" aria-label="Período">{filters}{refresh_button}</nav>
      <div class="usage-summary">
      <div class="panel stat"><p class="stat-label">Chamadas de IA</p><strong>{totals["calls"]:,}</strong>
        <span class="stat-sub"><span class="ok">{totals["completed"]} concluídas</span> · <span class="err">{totals["failed"]} falhas</span> · {totals["interrupted"]} interrompidas</span></div>
      <div class="panel stat"><p class="stat-label">Tokens de entrada + saída</p><strong>{totals["input_tokens"] + totals["output_tokens"]:,}</strong>
        <span class="stat-sub">{totals["input_tokens"]:,} entrada · {totals["output_tokens"]:,} saída</span></div>
      <div class="panel stat"><p class="stat-label">Custo equivalente de API</p><strong>{cost_main}</strong>{cost_sub}</div></div>
      <section class="panel"><h2>Tokens por modelo</h2>{usage_chart(buckets, start, end)}</section>
      <section class="panel"><h2>Detalhamento</h2><div class="usage-table-wrap"><table class="usage-table"><thead><tr><th>Modelo executado</th><th>Chamadas</th><th>Entrada</th><th>Cache¹</th><th>Saída</th><th>Estimativa USD</th></tr></thead>
      <tbody>{model_rows(buckets)}</tbody></table></div>
      <p class="muted">¹ Cache faz parte da entrada; não é somado novamente. Reasoning faz parte da saída.</p></section>
      <p class="muted">{unknown}</p>
      </div>"""


FILTER_SCRIPT = """<script>
  (function () {
    // Cache do fragmento por período: vive só nesta carga da página (F5 descarta).
    var fragmentCache = {};
    function seedCacheFromServerRender() {
      var container = document.getElementById('usage-content');
      var active = document.querySelector('.usage-filters a[aria-current]');
      if (container && active) {
        fragmentCache[active.getAttribute('data-days')] = container.outerHTML;
      }
    }
    function applyFragment(html, url) {
      var container = document.getElementById('usage-content');
      container.innerHTML = html;
      if (url) history.pushState({}, '', url);
      if (window.initUsageChart) window.initUsageChart();
    }
    function loadPeriod(days, cleanUrl, pushUrl) {
      if (fragmentCache[days]) { applyFragment(fragmentCache[days], pushUrl); return; }
      var nav = document.querySelector('.usage-filters');
      if (nav) nav.setAttribute('aria-busy', 'true');
      var partialUrl = cleanUrl + (cleanUrl.indexOf('?') > -1 ? '&' : '?') + 'partial=1';
      fetch(partialUrl, { headers: { Accept: 'application/json' }, redirect: 'error' })
        .then(function (response) {
          if (!response.ok) throw new Error('partial request failed');
          return response.json();
        })
        .then(function (data) {
          fragmentCache[days] = data.html;
          applyFragment(data.html, pushUrl);
        })
        .catch(function () { window.location.assign(cleanUrl); })
        .finally(function () {
          var busy = document.querySelector('.usage-filters[aria-busy="true"]');
          if (busy) busy.removeAttribute('aria-busy');
        });
    }
    document.addEventListener('click', function (event) {
      if (!event.target.closest) return;
      var link = event.target.closest('a[data-days]');
      var refresh = event.target.closest('[data-refresh]');
      if (!link && !refresh) return;
      var container = document.getElementById('usage-content');
      if (!container || !window.fetch) return;
      event.preventDefault();
      if (link) {
        loadPeriod(link.getAttribute('data-days'), link.href, link.href);
        return;
      }
      var active = document.querySelector('.usage-filters a[aria-current]');
      if (!active) return;
      fragmentCache = {};
      loadPeriod(active.getAttribute('data-days'), active.href, null);
    });
    window.addEventListener('popstate', function () { window.location.reload(); });
    seedCacheFromServerRender();
  })();
</script>"""


def render_usage(session: Session, user: User, days: int, admin: bool, root_path: str = "") -> str:
    root_path = html.escape(root_path.rstrip("/"), quote=True)
    base = f"{root_path}/backoffice/users/{user.id}/usage" if admin else f"{root_path}/dashboard"
    navigation = (
        f'<a href="{root_path}/backoffice">← backoffice</a>'
        if admin
        else f'<form method="post" action="{root_path}/dashboard/logout"><button class="btn small ghost">Sair do dashboard</button></form>'
    )
    catalog = session.get(PriceCatalog, 1)
    price_date = (
        catalog.fetched_at.strftime("%d/%m/%Y %H:%M UTC") if catalog else "ainda indisponível"
    )
    subscription = (
        ""
        if admin
        else f"""
    <section class="panel" aria-labelledby="subscription-heading">
      <h2 id="subscription-heading">Limites da assinatura</h2>
      <p class="muted">Dados atuais da sua conta Codex, incluindo uso fora deste proxy.
        Independentes do período selecionado e da estimativa de custo abaixo.</p>
      <div id="subscription-limits" aria-live="polite" data-url="{root_path}/dashboard/limits">
        <p class="muted">Consultando limites da assinatura…</p>
      </div>
      <noscript>Ative JavaScript para consultar os limites da assinatura.</noscript>
    </section>
    <script>
      (async function loadSubscriptionLimits() {{
        const target = document.getElementById('subscription-limits');
        try {{
          const response = await fetch(target.dataset.url, {{redirect: 'error', cache: 'no-store'}});
          if (!response.ok) throw new Error('Limits unavailable');
          target.innerHTML = await response.text();
        }} catch (error) {{
          target.textContent = 'Limites da assinatura indisponíveis no momento. Sua telemetria local continua disponível.';
        }}
      }})();
    </script>"""
    )
    content = render_period_content(session, user, days, base)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consumo — ChatGPT Proxy</title>{favicon_link(root_path)}{THEME_HEAD_SCRIPT}<style>{BASE_CSS}{USAGE_CSS}{THEME_TOGGLE_CSS}</style></head><body><div class="container">
    <header class="topbar"><a class="brand" href="{root_path}/">chatgpt-openai-proxy</a><nav>{navigation}{THEME_TOGGLE_HTML}</nav></header>
    <div class="rise" style="--d: 0"><p class="eyebrow"><span class="tick">///</span> TELEMETRIA · {"BACKOFFICE" if admin else "MINHA CONTA"}</p>
    <h1>Consumo de {html.escape(user.name)}</h1></div>
    {subscription}
    {content}
    <p class="muted">Preços OpenAI via models.dev, atualizados em {price_date}. Estimativa histórica calculada por chamada, não representa cobrança da assinatura ChatGPT.</p>
    <footer class="footer"><a href="{root_path}/#privacidade">Privacidade e retenção</a><span>Sem conteúdo de conversas armazenado.</span></footer></div>{THEME_TOGGLE_SCRIPT}{FILTER_SCRIPT}</body></html>"""
