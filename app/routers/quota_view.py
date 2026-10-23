"""Componente visual das janelas de cota, compartilhado por todos os providers.

Cada janela é uma régua de medição: trilho com marcas de 25/50/75%, preenchimento
com uma agulha na ponta (como a linha de cota de um desenho técnico) e o valor em
mono ao lado. O estado muda de cor, mas também de texto, nas faixas de uso alto.
"""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

CACHE_NOTE = "cache de até 60 segundos"
WARN_FROM = 70
CRITICAL_FROM = 90
LIMIT_REACHED_FROM = 100

LIMITS_CSS = """
:root { --warn-ink: #8a5a00; }
[data-theme="dark"] { --warn-ink: #e3b25a; }

.plan-row { margin: 0 0 1rem; }
.plan {
  display: inline-flex; align-items: baseline; gap: .55rem;
  font-family: var(--font-mono); font-size: .72rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: .15rem .75rem;
}
.plan strong { color: var(--ink); letter-spacing: .02em; font-weight: 500; text-transform: none; font-size: .8rem; }

.limit-state { margin: .2rem 0 .8rem; font-family: var(--font-mono); font-size: .78rem; color: var(--muted); }
.limit-state::before { content: "●"; margin-right: .45rem; }
.limit-state[data-tone="ok"]::before { color: var(--ok-ink); }
.limit-state[data-tone="warn"]::before { color: var(--warn-ink); }
.limit-state[data-tone="err"]::before { color: var(--err-ink); }

table.limits { width: 100%; table-layout: fixed; border-collapse: collapse; margin: .2rem 0 .6rem; }
table.limits th:nth-child(1), table.limits td.win { width: 11.5rem; }
table.limits th:nth-child(3), table.limits td.reset { width: 11rem; }
table.limits th {
  text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--line);
  font-family: var(--font-mono); font-size: .68rem; font-weight: 500; letter-spacing: .12em;
  text-transform: uppercase; color: var(--muted);
}
table.limits td { padding: .75rem .6rem; border-bottom: 1px solid var(--line); vertical-align: middle; }
table.limits tr:last-child td { border-bottom: 0; }
table.limits td.win { font-family: var(--font-mono); font-size: .85rem; }
table.limits td.reset { font-family: var(--font-mono); font-size: .78rem; white-space: nowrap; }
table.limits td.reset .rel { display: block; color: var(--muted); }

.limit-note { margin: .35rem 0; font-family: var(--font-mono); font-size: .8rem; }
.limits-foot { margin: .9rem 0 0; font-family: var(--font-mono); font-size: .72rem; color: var(--muted); }

.use-cell { display: flex; align-items: center; gap: 1rem; }
.meter {
  position: relative; flex: 1 1 6rem; min-width: 6rem; height: .7rem;
  border: 1px solid var(--line); border-radius: 2px; background-color: var(--surface);
  background-image: repeating-linear-gradient(90deg, transparent 0, transparent calc(25% - 1px), var(--line) calc(25% - 1px), var(--line) 25%);
}
.meter-fill {
  position: absolute; inset: 0 auto 0 0; width: var(--w); background: var(--link);
  animation: meter-sweep 700ms var(--ease-out) both; animation-delay: calc(var(--i, 0) * 70ms);
}
.meter-fill::after {
  content: ""; position: absolute; right: -1px; top: -.28rem; bottom: -.28rem; width: 2px; background: inherit;
}
.meter[data-empty] .meter-fill::after { display: none; }
.meter[data-state="warn"] .meter-fill { background: var(--warn-ink); }
.meter[data-state="crit"] .meter-fill, .meter[data-state="full"] .meter-fill { background: var(--err-ink); }
@keyframes meter-sweep { from { width: 0; } }

.pct { font-family: var(--font-mono); font-size: .8rem; white-space: nowrap; min-width: 6.8rem; }
.pct strong { font-weight: 500; }
.pct em { display: block; font-style: normal; font-size: .72rem; color: var(--warn-ink); }
.pct[data-state="crit"] em, .pct[data-state="full"] em { color: var(--err-ink); }

@media (prefers-reduced-motion: reduce) { .meter-fill { animation: none; } }

@media (max-width: 560px) {
  table.limits, table.limits tbody, table.limits tr, table.limits td { display: block; }
  table.limits thead { display: none; }
  table.limits tr { padding: .7rem 0; border-bottom: 1px solid var(--line); }
  table.limits tr:last-child { border-bottom: 0; }
  table.limits td { border: 0; padding: .15rem 0; width: auto; }
}
"""


@dataclass(frozen=True)
class WindowRow:
    """Uma janela de cota: rótulo, % já usado e quando renova (None = não informado)."""

    label: str
    used_percent: float
    reset: datetime | None


def window_label(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} dias"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} horas"
    return f"{seconds / 60:g} minutos"


def usage_state(used_percent: float) -> str:
    """Faixa de uso: ``ok``, ``warn``, ``crit`` ou ``full``."""
    if used_percent >= LIMIT_REACHED_FROM:
        return "full"
    if used_percent >= CRITICAL_FROM:
        return "crit"
    if used_percent >= WARN_FROM:
        return "warn"
    return "ok"


_STATE_NOTE = {"warn": "uso alto", "crit": "quase no limite", "full": "limite atingido"}


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def format_remaining(reset: datetime, as_of: datetime) -> str:
    """Tempo até a renovação, em texto curto (``em 2 h 14 min``)."""
    seconds = int((_as_utc(reset) - _as_utc(as_of)).total_seconds())
    if seconds <= 0:
        return "renovando agora"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"em {days} d {hours} h"
    if hours:
        return f"em {hours} h {minutes} min"
    return f"em {max(minutes, 1)} min"


def render_plan(plan: str | None) -> str:
    if not plan:
        return ""
    return f'<p class="plan-row"><span class="plan">plano <strong>{html.escape(plan)}</strong></span></p>'


def render_limit_state(text: str, tone: str) -> str:
    """Linha de estado de um limite (``ok``, ``warn``, ``err`` ou ``muted``)."""
    return f'<p class="limit-state" data-tone="{tone}">{html.escape(text)}</p>'


def render_footer(fetched_at: datetime) -> str:
    return f'<p class="limits-foot">Consultado em {fetched_at:%d/%m/%Y %H:%M:%S} UTC · {CACHE_NOTE}.</p>'


def render_window_table(rows: Sequence[WindowRow], as_of: datetime) -> str:
    """Tabela Janela | Usado (régua e valor) | Renovação."""
    body = "".join(_render_row(index, row, as_of) for index, row in enumerate(rows))
    return (
        '<table class="limits"><thead><tr>'
        "<th>Janela</th><th>Usado</th><th>Renovação</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _render_row(index: int, row: WindowRow, as_of: datetime) -> str:
    label = html.escape(row.label)
    state = usage_state(row.used_percent)
    width = max(0.0, min(row.used_percent, 100.0))
    note = f"<em>{_STATE_NOTE[state]}</em>" if state in _STATE_NOTE else ""
    empty = " data-empty" if width == 0 else ""
    return (
        f'<tr><td class="win">{label}</td>'
        f'<td class="use"><div class="use-cell">'
        f'<div class="meter" data-state="{state}"{empty} role="progressbar" aria-valuemin="0" '
        f'aria-valuemax="100" aria-valuenow="{width:g}" aria-label="Uso da janela de {label}">'
        f'<span class="meter-fill" style="--w:{width:g}%;--i:{index}"></span></div>'
        f'<span class="pct" data-state="{state}"><strong>{row.used_percent:g}% usado</strong>{note}</span>'
        f"</div></td>"
        f'<td class="reset">{_render_reset(row.reset, as_of)}</td></tr>'
    )


def _render_reset(reset: datetime | None, as_of: datetime) -> str:
    if reset is None:
        return '<span class="muted">não informado</span>'
    return f'{reset:%d/%m/%Y %H:%M} UTC<span class="rel">{format_remaining(reset, as_of)}</span>'
