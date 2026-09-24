"""Engine, sessão e inicialização do banco de dados.

Usa SQLModel/SQLAlchemy síncrono: os endpoints FastAPI rodam em threadpool e
o acesso ao banco é curto (o streaming SSE em si não toca o banco). Funciona
com SQLite local e com Postgres gerenciado (ex.: Neon no FastAPI Cloud) via
DATABASE_URL. A criação de tabelas é idempotente (`CREATE TABLE IF NOT
EXISTS`), segura para deploys zero-downtime com múltiplas instâncias.
"""

import os
from collections.abc import Generator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, Session, create_engine

from .config import get_settings

_engine: Engine | None = None


def _make_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # check_same_thread=False é seguro: o Session é por-request e o
        # FastAPI isola requisições em threads do pool.
        kwargs["connect_args"] = {"check_same_thread": False}

        @event.listens_for(Engine, "connect")
        def _sqlite_fk(dbapi_conn, _record):  # noqa: ANN001, ANN202
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return create_engine(url, **kwargs)


def get_engine() -> Engine:
    """Retorna (criando se necessário) o engine global."""
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite"):
            # Garante que o diretório do arquivo existe (ex.: ./data/proxy.db).
            path = url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        _engine = _make_engine()
    return _engine


def init_db() -> None:
    """Cria as tabelas se não existirem (idempotente, seguro no boot)."""
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Generator[Session, None, None]:
    """Dependency FastAPI que fornece uma sessão por requisição."""
    with Session(get_engine()) as session:
        yield session


def reset_engine() -> None:
    """Descarta o engine global (usado em testes para trocar o DATABASE_URL)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
