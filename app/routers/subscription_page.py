import html
from datetime import UTC, datetime, timedelta

from ..subscription_models import LimitWindow, RateLimit, SubscriptionResult


def window_label(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} dias"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} horas"
    return f"{seconds / 60:g} minutos"


def render_window(window: LimitWindow, fetched_at: datetime) -> str:
    reset = (
        datetime.fromtimestamp(window.reset_at, UTC)
        if window.reset_at is not None
        else fetched_at + timedelta(seconds=window.reset_after_seconds)
        if window.reset_after_seconds is not None
        else None
    )
    reset_label = reset.strftime("%d/%m/%Y %H:%M UTC") if reset else "não informado"
    duration = window_label(window.limit_window_seconds)
    return (
        f"<p>{duration}: <strong>{window.used_percent:g}% usado</strong></p>"
        f'<progress max="100" value="{min(window.used_percent, 100):g}" '
        f'aria-label="Uso da janela de {duration}"></progress>'
        f'<p class="muted">Renovação: {reset_label}</p>'
    )


def render_limit(label: str, limit: RateLimit, fetched_at: datetime) -> str:
    state = (
        "Limite atingido"
        if limit.limit_reached is True
        else "Temporariamente indisponível"
        if limit.allowed is False
        else "Disponível"
        if limit.allowed is True
        else "Estado não informado"
    )
    windows = "".join(
        render_window(window, fetched_at)
        for window in (limit.primary_window, limit.secondary_window)
        if window is not None
    )
    return f"<div><h3>{html.escape(label)}</h3><p>{state}</p>{windows}</div>"


def render_subscription(result: SubscriptionResult) -> str:
    if not result.available or result.usage is None:
        return '<p class="muted">Limites da assinatura indisponíveis no momento. Sua telemetria local continua disponível.</p>'
    usage = result.usage
    sections = []
    if usage.plan_type:
        sections.append(f"<p>Plano: <strong>{html.escape(usage.plan_type)}</strong></p>")
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
            sections.append("<p>Créditos: sem limite informado pelo provedor.</p>")
        elif credits.balance is not None:
            sections.append(f"<p>Saldo de créditos: {credits.balance:g}</p>")
        elif credits.has_credits is not None:
            sections.append(
                "<p>Créditos disponíveis.</p>"
                if credits.has_credits
                else "<p>Sem créditos disponíveis.</p>"
            )
    if (
        usage.rate_limit_reset_credits
        and usage.rate_limit_reset_credits.available_count is not None
    ):
        sections.append(
            f"<p>Reinícios de limite disponíveis: {usage.rate_limit_reset_credits.available_count}</p>"
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
            f"<p>{html.escape(model)}: {state}{' · previsão: ' + when if when else ''}</p>"
        )
    sections.append(
        f'<p class="muted">Consultado em {result.fetched_at:%d/%m/%Y %H:%M:%S} UTC · cache de até 60 segundos.</p>'
    )
    return "".join(sections)
