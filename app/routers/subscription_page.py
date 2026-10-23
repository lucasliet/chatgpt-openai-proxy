import html
from datetime import UTC, datetime, timedelta

from ..subscription_models import LimitWindow, RateLimit, SubscriptionResult
from .quota_view import (
    WindowRow,
    render_footer,
    render_limit_state,
    render_plan,
    render_window_table,
    window_label,
)


def window_row(window: LimitWindow, fetched_at: datetime) -> WindowRow:
    reset = (
        datetime.fromtimestamp(window.reset_at, UTC)
        if window.reset_at is not None
        else fetched_at + timedelta(seconds=window.reset_after_seconds)
        if window.reset_after_seconds is not None
        else None
    )
    return WindowRow(window_label(window.limit_window_seconds), window.used_percent, reset)


def _limit_state(limit: RateLimit) -> tuple[str, str]:
    if limit.limit_reached is True:
        return "Limite atingido", "err"
    if limit.allowed is False:
        return "Temporariamente indisponível", "warn"
    if limit.allowed is True:
        return "Disponível", "ok"
    return "Estado não informado", "muted"


def render_limit(label: str, limit: RateLimit, fetched_at: datetime) -> str:
    state_text, tone = _limit_state(limit)
    rows = [
        window_row(window, fetched_at)
        for window in (limit.primary_window, limit.secondary_window)
        if window is not None
    ]
    table = render_window_table(rows, fetched_at) if rows else ""
    return f"<div><h3>{html.escape(label)}</h3>{render_limit_state(state_text, tone)}{table}</div>"


def render_subscription(result: SubscriptionResult) -> str:
    if not result.available or result.usage is None:
        return '<p class="muted">Limites da assinatura indisponíveis no momento. Sua telemetria local continua disponível.</p>'
    usage = result.usage
    sections = []
    if usage.plan_type:
        sections.append(render_plan(usage.plan_type))
    for label, limit in (
        ("Uso do Codex", usage.rate_limit),
        ("Revisão de código", usage.code_review_rate_limit),
    ):
        if limit is not None:
            sections.append(render_limit(label, limit, result.fetched_at))
    for named in usage.additional_rate_limits or []:
        if named.rate_limit is not None:
            sections.append(
                render_limit(
                    named.limit_name or named.metered_feature or "Limite adicional",
                    named.rate_limit,
                    result.fetched_at,
                )
            )
    if usage.credits:
        credits = usage.credits
        if credits.unlimited is True:
            sections.append(
                "<p class='limit-note'>Créditos: sem limite informado pelo provedor.</p>"
            )
        elif credits.balance is not None:
            sections.append(f"<p class='limit-note'>Saldo de créditos: {credits.balance:g}</p>")
        elif credits.has_credits is not None:
            sections.append(
                "<p class='limit-note'>Créditos disponíveis.</p>"
                if credits.has_credits
                else "<p class='limit-note'>Sem créditos disponíveis.</p>"
            )
    if (
        usage.rate_limit_reset_credits
        and usage.rate_limit_reset_credits.available_count is not None
    ):
        sections.append(
            f"<p class='limit-note'>Reinícios de limite disponíveis: {usage.rate_limit_reset_credits.available_count}</p>"
        )
    for model, availability in (usage.model_usage or {}).items():
        state = (
            "Disponível"
            if availability.available is True
            else "Indisponível"
            if availability.available is False
            else "Disponibilidade não informada"
        )
        when = (
            availability.available_at.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")
            if availability.available_at
            else None
        )
        sections.append(
            f"<p class='limit-note'>{html.escape(model)}: {state}{' · previsão: ' + when if when else ''}</p>"
        )
    sections.append(render_footer(result.fetched_at))
    return "".join(sections)
