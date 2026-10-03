"""Engine, sessão e inicialização do banco de dados.

Usa SQLModel/SQLAlchemy síncrono: os endpoints FastAPI rodam em threadpool e
o acesso ao banco é curto (o streaming SSE em si não toca o banco). Funciona
com SQLite local e com Postgres gerenciado (ex.: Neon no FastAPI Cloud) via
DATABASE_URL. A criação de tabelas é idempotente (`CREATE TABLE IF NOT
EXISTS`), segura para deploys zero-downtime com múltiplas instâncias.
"""

import os
from collections.abc import Generator

from sqlalchemy import BIGINT, event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings, resolved_database_url

_engine: Engine | None = None

# Colunas adicionadas ao longo da vida do projeto para a tabela proxy_user.
# `create_all` não altera tabelas existentes, então aplicamos ALTER TABLE
# idempotente no boot (seguro com múltiplas instâncias: ADD COLUMN IF NOT
# EXISTS é verificado por inspeção antes).
_USER_COLUMN_MIGRATIONS: dict[str, str] = {
    "account_id": "ALTER TABLE proxy_user ADD COLUMN account_id VARCHAR",
    "access_token": "ALTER TABLE proxy_user ADD COLUMN access_token VARCHAR NOT NULL DEFAULT ''",
    "refresh_token": "ALTER TABLE proxy_user ADD COLUMN refresh_token VARCHAR NOT NULL DEFAULT ''",
    "expires_at": "ALTER TABLE proxy_user ADD COLUMN expires_at BIGINT NOT NULL DEFAULT 0",
    "last_login_at": "ALTER TABLE proxy_user ADD COLUMN last_login_at TIMESTAMP",
}


def _normalize_url(url: str) -> str:
    """Normaliza DATABASE_URL para o driver disponível.

    Postgres gerenciado (Neon/FastAPI Cloud) costuma vir como ``postgres://``
    ou ``postgresql://``; o SQLAlchemy associa esse último ao psycopg2, mas o
    projeto empacota o psycopg 3 — então forçamos o dialect ``psycopg``.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _make_engine() -> Engine:
    url = _normalize_url(resolved_database_url(get_settings()))
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
        url = resolved_database_url(get_settings())
        if url.startswith("sqlite"):
            # Garante que o diretório do arquivo existe e tem permissão
            # restritiva (mesmo cuidado do credentials.json 0600 original).
            from .config import proxy_home

            home = proxy_home(get_settings())
            home.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(home, 0o700)
            except OSError:
                pass
            db_path = home / "proxy.db"
            try:
                if db_path.exists():
                    os.chmod(db_path, 0o600)
            except OSError:
                pass
        _engine = _make_engine()
    return _engine


def _run_column_migrations(engine: Engine) -> None:
    """Adiciona colunas novas em tabelas existentes (idempotente)."""
    inspector = inspect(engine)
    if "proxy_user" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("proxy_user")}
    pending = [
        statement for column, statement in _USER_COLUMN_MIGRATIONS.items() if column not in existing
    ]
    if not pending:
        return
    with engine.begin() as connection:
        for statement in pending:
            connection.execute(text(statement))


def _ensure_user_column_types(engine: Engine) -> None:
    """Corrige tipos de colunas em bancos criados por versões antigas.

    ``expires_at`` guarda epoch em milissegundos (~1,79e12 hoje), que não
    cabe no INTEGER de 32 bits do Postgres. Bancos criados quando o modelo
    usava ``int`` puro têm a coluna como INTEGER e precisam de ALTER COLUMN;
    o SQLite tem inteiros de 64 bits nativos e não precisa de correção.
    """
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    if "proxy_user" not in inspector.get_table_names():
        return
    for column in inspector.get_columns("proxy_user"):
        if column["name"] == "expires_at" and not isinstance(column["type"], BIGINT):
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE proxy_user ALTER COLUMN expires_at TYPE BIGINT")
                )
            break


def _encrypt_existing_tokens(engine: Engine) -> None:
    """Cifra tokens legados em texto puro e rotaciona chaves antigas.

    Roda via SQL cru (sem o ORM) para não passar pelo ``EncryptedText`` —
    aqui o ponto é justamente inspecionar o valor físico. Idempotente:
    ``upgraded_ciphertext`` retorna None para quem já está na chave primária.
    Também é aqui que o keyring é resolvido no boot: com ``DATABASE_URL`` e
    sem ``TOKEN_ENCRYPTION_KEY`` o erro acontece antes de servir tráfego.
    """
    from .crypto import get_keyring, upgraded_ciphertext

    # Resolve o keyring no boot, mesmo sem dados: com DATABASE_URL e sem
    # TOKEN_ENCRYPTION_KEY o erro acontece antes de servir tráfego.
    get_keyring()

    inspector = inspect(engine)
    if "proxy_user" not in inspector.get_table_names():
        return
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, access_token, refresh_token FROM proxy_user")
        ).all()
        for row in rows:
            for column in ("access_token", "refresh_token"):
                value = getattr(row, column)
                new_value = upgraded_ciphertext(value) if value else None
                if new_value is not None:
                    connection.execute(
                        text(f"UPDATE proxy_user SET {column} = :value WHERE id = :id"),
                        {"value": new_value, "id": row.id},
                    )


def init_db() -> None:
    """Cria as tabelas se não existirem (idempotente, seguro no boot)."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _run_column_migrations(engine)
    _ensure_user_column_types(engine)
    _encrypt_existing_tokens(engine)


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
