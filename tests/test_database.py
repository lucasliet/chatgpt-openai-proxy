"""Testes de normalização do DATABASE_URL para o driver psycopg 3."""

from app.database import _normalize_url


class TestNormalizeUrl:
    def test_postgres_antigo(self):
        assert (
            _normalize_url("postgres://u:p@host/db")
            == "postgresql+psycopg://u:p@host/db"
        )

    def test_postgresql_sem_driver(self):
        assert (
            _normalize_url("postgresql://u:p@host/db")
            == "postgresql+psycopg://u:p@host/db"
        )

    def test_com_driver_explicito_preserve(self):
        url = "postgresql+psycopg://u:p@host/db"
        assert _normalize_url(url) == url

    def test_sqlite_inalterado(self):
        url = "sqlite:///./data/proxy.db"
        assert _normalize_url(url) == url
