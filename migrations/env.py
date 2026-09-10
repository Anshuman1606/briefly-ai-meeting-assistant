"""Alembic environment supporting both CLI and an existing app transaction."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from briefly.models import Base


config = context.config
target_metadata = Base.metadata


def _url():
    value = os.getenv("DATABASE_URL", "")
    if not value:
        raise RuntimeError("Set DATABASE_URL to run migrations from the command line.")
    if value.startswith(("postgres://", "postgresql://")):
        value = "postgresql+psycopg://" + value.split("://", 1)[1]
    return value


def _run(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    provided = config.attributes.get("connection")
    if provided is not None:
        _run(provided)
    else:
        engine = create_engine(_url(), poolclass=pool.NullPool, hide_parameters=True)
        try:
            with engine.begin() as connection:
                if connection.dialect.name == "postgresql":
                    from sqlalchemy import text
                    connection.execute(text("SELECT pg_advisory_xact_lock(764183290)"))
                _run(connection)
        finally:
            engine.dispose()
