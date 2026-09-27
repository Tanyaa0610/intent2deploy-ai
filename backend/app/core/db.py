from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


# Tables from a retired schema generation that are superseded by a
# differently-shaped replacement (not a parallel/duplicate system — the
# replacement lives at the same conceptual place, just a new table name).
# Dropped on startup because they hold only regenerable audit data, never
# user-authored work.
_RETIRED_TABLES = {"guardrailevent": "guardrailcheck"}  # old name -> new name


def init_db() -> None:
    # Import models so SQLModel metadata is populated before create_all.
    from app import models  # noqa: F401

    _drop_retired_tables()
    SQLModel.metadata.create_all(engine)
    _migrate_add_missing_columns()


def _drop_retired_tables() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for old_name in _RETIRED_TABLES:
            if old_name in existing_tables:
                conn.execute(text(f'DROP TABLE "{old_name}"'))


def _migrate_add_missing_columns() -> None:
    """`create_all` only creates tables that don't yet exist — it never
    alters an existing table's columns. This project has no Alembic
    migration chain, so for the local SQLite dev database we apply a
    minimal, additive `ALTER TABLE ADD COLUMN` (nullable, no DEFAULT clause
    to avoid SQLite's limited expression support there) for any column the
    current models declare that an already-existing table is missing, then
    backfill existing rows with the model's Python-side default. This never
    drops or rewrites other data."""
    if not settings.database_url.startswith("sqlite"):
        return
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}'))

                default_value = None
                if column.default is not None and getattr(column.default, "arg", None) is not None and not callable(column.default.arg):
                    default_value = column.default.arg
                    if hasattr(default_value, "name") and hasattr(default_value, "value"):
                        # SQLAlchemy's Enum column stores the member NAME by
                        # default (not `.value`) — match that convention.
                        default_value = default_value.name
                if default_value is not None:
                    conn.execute(
                        text(f'UPDATE "{table_name}" SET "{column.name}" = :val WHERE "{column.name}" IS NULL'),
                        {"val": default_value},
                    )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
