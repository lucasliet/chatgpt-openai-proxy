"""Componente visual das janelas de cota: faixas de estado, renovação e escape."""

from datetime import UTC, datetime, timedelta

import pytest

from app.routers.quota_view import (
    WindowRow,
    format_remaining,
    render_footer,
    render_limit_state,
    render_plan,
    render_window_table,
    usage_state,
    window_label,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


class TestUsageState:
    @pytest.mark.parametrize(
        ("percent", "state"),
        [
            (0, "ok"),
            (69.9, "ok"),
            (70, "warn"),
            (89.9, "warn"),
            (90, "crit"),
            (99.9, "crit"),
            (100, "full"),
            (101, "full"),
        ],
    )
    def test_faixas_de_uso(self, percent, state):
        assert usage_state(percent) == state


class TestFormatRemaining:
    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(days=3, hours=4, minutes=5), "em 3 d 4 h"),
            (timedelta(hours=2, minutes=14, seconds=30), "em 2 h 14 min"),
            (timedelta(minutes=14), "em 14 min"),
            (timedelta(seconds=20), "em 1 min"),
            (timedelta(seconds=0), "renovando agora"),
            (timedelta(minutes=-5), "renovando agora"),
        ],
    )
    def test_texto_curto_por_faixa(self, delta, expected):
        assert format_remaining(NOW + delta, NOW) == expected

    def test_aceita_datas_sem_fuso_como_utc(self):
        naive_reset = (NOW + timedelta(hours=1)).replace(tzinfo=None)
        assert format_remaining(naive_reset, NOW) == "em 1 h 0 min"


class TestRenderWindowTable:
    def _render(self, *rows: WindowRow) -> str:
        return render_window_table(list(rows), NOW)

    def test_linha_normal_tem_regua_valor_e_renovacao(self):
        html = self._render(WindowRow("5 horas", 23, NOW + timedelta(hours=2, minutes=14)))

        assert '<td class="win">5 horas</td>' in html
        assert 'role="progressbar"' in html
        assert 'aria-valuenow="23"' in html
        assert "--w:23%" in html
        assert "<strong>23% usado</strong>" in html
        assert "23/10/2026 14:14 UTC" in html
        assert "em 2 h 14 min" in html
        assert "<em>" not in html

    @pytest.mark.parametrize(
        ("percent", "state", "note"),
        [
            (75, "warn", "uso alto"),
            (95, "crit", "quase no limite"),
            (100, "full", "limite atingido"),
        ],
    )
    def test_faixas_altas_tem_texto_alem_da_cor(self, percent, state, note):
        html = self._render(WindowRow("7 dias", percent, None))

        assert f'data-state="{state}"' in html
        assert f"<em>{note}</em>" in html

    def test_uso_acima_de_100_e_limitado_na_regua_mas_nao_no_texto(self):
        html = self._render(WindowRow("5 horas", 101, None))

        assert "--w:100%" in html
        assert 'aria-valuenow="100"' in html
        assert "101% usado" in html

    def test_uso_zero_esconde_a_agulha(self):
        html = self._render(WindowRow("5 horas", 0, None))

        assert " data-empty " in html
        assert "--w:0%" in html

    def test_sem_renovacao_informa_que_nao_ha_data(self):
        assert "não informado" in self._render(WindowRow("5 horas", 10, None))

    def test_rotulo_e_escapado(self):
        html = self._render(WindowRow("<script>x</script>", 10, None))

        assert "<script>x</script>" not in html
        assert "&lt;script&gt;x&lt;/script&gt;" in html

    def test_cada_linha_recebe_um_indice_para_o_escalonamento_da_animacao(self):
        html = self._render(WindowRow("a", 1, None), WindowRow("b", 2, None))

        assert "--i:0" in html
        assert "--i:1" in html


class TestPequenosComponentes:
    def test_plano_e_escapado(self):
        assert "plano <strong>&lt;b&gt;</strong>" in render_plan("<b>")

    def test_sem_plano_nao_renderiza_nada(self):
        assert render_plan(None) == ""

    def test_estado_do_limite_usa_o_tom(self):
        assert 'data-tone="ok">Disponível<' in render_limit_state("Disponível", "ok")

    def test_rodape_informa_horario_e_cache(self):
        footer = render_footer(datetime(2026, 10, 23, 2, 2, 43, tzinfo=UTC))
        assert "23/10/2026 02:02:43 UTC" in footer
        assert "cache de até 60 segundos" in footer

    @pytest.mark.parametrize(
        ("seconds", "label"),
        [(18000, "5 horas"), (604800, "7 dias"), (2_592_000, "30 dias"), (90, "1.5 minutos")],
    )
    def test_rotulo_da_janela_vem_da_duracao(self, seconds, label):
        assert window_label(seconds) == label
