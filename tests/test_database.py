"""Testes do banco: normalização de URL e storage local sem DATABASE_URL."""

from sqlalchemy import BigInteger

from app.config import Settings, resolved_database_url
from app.database import _normalize_url
from app.models import User


def test_expires_at_e_bigint_no_modelo():
    """Epoch em ms (~1,79e12) não cabe no INTEGER de 32 bits do Postgres."""
    assert isinstance(User.__table__.c.expires_at.type, BigInteger)


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


class TestStorageLocalSemDatabaseUrl:
    """Sem DATABASE_URL, o estado fica em arquivo no CHATGPT_PROXY_HOME."""

    def test_fallback_para_proxy_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHATGPT_PROXY_HOME", str(tmp_path / "home"))
        settings = Settings(database_url=None)
        assert resolved_database_url(settings) == f"sqlite:///{tmp_path}/home/proxy.db"

    def test_database_url_tem_precedencia(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHATGPT_PROXY_HOME", str(tmp_path / "home"))
        settings = Settings(database_url="postgresql://u:p@host/db")
        assert resolved_database_url(settings) == "postgresql://u:p@host/db"
