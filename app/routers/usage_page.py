import html
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
)

USAGE_CSS = """
.topbar { flex-wrap:wrap; }
.usage-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; }
.usage-summary strong { display:block; font-family:var(--font-mono); font-size:clamp(1.1rem,3vw,1.8rem); overflow-wrap:anywhere; }
.usage-summary p { margin:0; }
.usage-filters { display:flex; gap:.5rem; flex-wrap:wrap; margin:1.5rem 0; }
.usage-filters [aria-current] { border-color:var(--link); color:var(--link); }
.usage-chart { width:100%; height:auto; display:block; }
.usage-chart text { fill:var(--muted); font-family:var(--font-mono); font-size:12px; }
.usage-table-wrap { overflow-x:auto; }
.usage-table { width:100%; border-collapse:collapse; font-family:var(--font-mono); font-size:.8rem; }
.usage-table th,.usage-table td { text-align:right; padding:.6rem; border-bottom:1px solid var(--line); white-space:nowrap; }
.usage-table th:first-child,.usage-table td:first-child { text-align:left; }
.usage-legend { display:flex; flex-wrap:wrap; gap:1rem; font-family:var(--font-mono); font-size:.8rem; }
.usage-legend span { border-bottom:3px solid; }
@media(max-width:600px) { .usage-summary { grid-template-columns:1fr; } }
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


def usage_chart(buckets: list[UsageBucket], start: datetime, end: datetime) -> str:
    if not buckets:
        return '<p class="muted">Ainda não há chamadas de IA neste período.</p>'
    models = sorted({bucket.model for bucket in buckets})
    colors = ("var(--link)", "var(--ok-ink)", "var(--err-ink)", "var(--muted)")
    hours = int((end - start).total_seconds() // 3600) + 1
    values = {model: [0] * hours for model in models}
    for bucket in buckets:
        position = int((bucket.hour - start).total_seconds() // 3600)
        if 0 <= position < hours:
            values[bucket.model][position] += bucket.input_tokens + bucket.output_tokens
    peak = max(max(series) for series in values.values()) or 1
    paths, legend = [], []
    for index, model in enumerate(models):
        color = colors[index % len(colors)]
        points = " ".join(
            f"{55 + hour * 690 / max(hours - 1, 1):.1f},{210 - value * 170 / peak:.1f}"
            for hour, value in enumerate(values[model])
        )
        paths.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{("none", "6 3", "2 3", "8 3 2 3")[index % 4]}"/>'
        )
        legend.append(f'<span style="border-color:{color}">{html.escape(model)}</span>')
    peak_label = (
        f"{peak / 1_000_000:.1f}M"
        if peak >= 1_000_000
        else f"{peak / 1000:.1f}K"
        if peak >= 1000
        else str(peak)
    )
    return f"""<svg class="usage-chart" viewBox="0 0 780 260" role="img" aria-label="Tokens por hora UTC e modelo. Totais disponíveis na tabela abaixo.">
    <path d="M55 40H745 M55 125H745 M55 210H745" stroke="var(--line)"/>
    <text x="5" y="40">{peak_label}</text><text x="30" y="210">0</text>
    {"".join(paths)}<text x="55" y="245">{start:%d/%m %Hh}</text><text x="640" y="245">{end:%d/%m %Hh}</text>
    </svg><div class="usage-legend">{"".join(legend)}</div>"""


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


def render_usage(session: Session, user: User, days: int, admin: bool) -> str:
    now = utcnow()
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
    cost = format_cost(totals)
    base = f"/backoffice/users/{user.id}/usage" if admin else "/dashboard"
    filters = "".join(
        f'<a class="btn small ghost" href="{base}?days={period}" {"aria-current=page" if days == period else ""}>{label}</a>'
        for period, label in ((1, "Hoje"), (7, "7 dias"), (30, "30 dias"))
    )
    navigation = (
        '<a href="/backoffice">← backoffice</a>'
        if admin
        else '<form method="post" action="/dashboard/logout"><button class="btn small ghost">Sair do dashboard</button></form>'
    )
    catalog = session.get(PriceCatalog, 1)
    price_date = (
        catalog.fetched_at.strftime("%d/%m/%Y %H:%M UTC") if catalog else "ainda indisponível"
    )
    unknown = (
        f"{totals['unknown_usage']} chamadas sem uso informado · {totals['unpriced']} sem estimativa. O custo exibido pode ser parcial."
        if totals["unpriced"]
        else "Todas as chamadas do período têm estimativa."
    )
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Consumo — ChatGPT Proxy</title>{THEME_HEAD_SCRIPT}<style>{BASE_CSS}{USAGE_CSS}{THEME_TOGGLE_CSS}</style></head><body><div class="container">
    <header class="topbar"><a class="brand" href="/">chatgpt-openai-proxy</a><nav>{navigation}{THEME_TOGGLE_HTML}</nav></header>
    <div class="rise" style="--d: 0"><p class="eyebrow"><span class="tick">///</span> TELEMETRIA · {"BACKOFFICE" if admin else "MINHA CONTA"}</p>
    <h1>Consumo de {html.escape(user.name)}</h1><p class="muted">{start:%d/%m/%Y %H:%M} → {now:%d/%m/%Y %H:%M} UTC · retenção de 30 dias</p></div>
    <nav class="usage-filters" aria-label="Período">{filters}</nav>
    <div class="usage-summary rise" style="--d: 1"><div class="panel"><p>Chamadas de IA</p><strong>{totals["calls"]:,}</strong></div>
    <div class="panel"><p>Tokens de entrada + saída</p><strong>{totals["input_tokens"] + totals["output_tokens"]:,}</strong></div>
    <div class="panel"><p>Custo equivalente de API</p><strong>{cost}</strong></div></div>
    <p class="muted">{totals["completed"]} concluídas · {totals["failed"]} falhas · {totals["interrupted"]} interrompidas</p>
    <section class="panel rise" style="--d: 2"><h2>Tokens por modelo</h2>{usage_chart(buckets, start, end)}</section>
    <section class="panel rise" style="--d: 3"><h2>Detalhamento</h2><div class="usage-table-wrap"><table class="usage-table"><thead><tr><th>Modelo executado</th><th>Chamadas</th><th>Entrada</th><th>Cache¹</th><th>Saída</th><th>Estimativa USD</th></tr></thead>
    <tbody>{model_rows(buckets)}</tbody></table></div>
    <p class="muted">¹ Cache faz parte da entrada; não é somado novamente. Reasoning faz parte da saída.</p></section>
    <p class="muted">{unknown}</p><p class="muted">Preços OpenAI via models.dev, atualizados em {price_date}. Estimativa histórica calculada por chamada, não representa cobrança da assinatura ChatGPT.</p>
    <footer class="footer"><a href="/#privacidade">Privacidade e retenção</a><span>Sem conteúdo de conversas armazenado.</span></footer></div>{THEME_TOGGLE_SCRIPT}</body></html>"""
