"""Apply reviewed migrations and fail closed on unversioned or drifted schemas."""

from pathlib import Path
import threading

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from briefly.models import Base


_ROOT = Path(__file__).resolve().parent.parent
_MIGRATION_LOCK = threading.RLock()


class SchemaError(RuntimeError):
    """A safe startup error, with no connection URL or SQL parameters."""


def migration_config(connection: Connection | None = None) -> Config:
    """Resolve migration files relative to the installed project, never the cwd."""
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "migrations").replace("%", "%%"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _owned_objects(obj, name, type_, reflected, compare_to):
    # A database may contain another application's tables; never manage those.
    return not (type_ == "table" and reflected and name not in Base.metadata.tables)


def _ensure(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(764183290)"))
    config = migration_config(connection)
    scripts = ScriptDirectory.from_config(config)
    migration = MigrationContext.configure(connection)
    current = migration.get_current_heads()
    application_tables = set(inspect(connection).get_table_names()) & set(Base.metadata.tables)
    if not current and application_tables:
        raise SchemaError(
            "Existing application tables have no migration history. Back up the database and "
            "have an administrator review an explicit baseline migration; automatic stamping is disabled."
        )
    for revision in current:
        try:
            scripts.get_revision(revision)
        except Exception:
            raise SchemaError("The database migration version is not supported by this deployment.") from None
    command.upgrade(config, "head")
    migration = MigrationContext.configure(connection, opts={
        "compare_type": True, "compare_server_default": False, "include_object": _owned_objects,
    })
    if set(migration.get_current_heads()) != set(scripts.get_heads()):
        raise SchemaError("The database did not reach the required migration version.")
    # Alembic does not reliably report primary-key changes in autogenerate.
    # Missing keys would invalidate tenant joins and atomic job ownership.
    inspector = inspect(connection)
    primary_key_drift = any(
        inspector.get_pk_constraint(table.name).get("constrained_columns", [])
        != [column.name for column in table.primary_key.columns]
        for table in Base.metadata.sorted_tables
        if inspector.has_table(table.name)
    )
    if primary_key_drift or compare_metadata(migration, Base.metadata):
        raise SchemaError(
            "The database schema differs from the deployed models. Apply reviewed migrations before starting the app."
        )


def ensure_schema(bind: Engine | Connection) -> None:
    """Upgrade and validate a database, preserving a caller's existing transaction.

    PostgreSQL startup is serialized with a transaction-level advisory lock.
    The process lock also protects Alembic's shared environment from concurrent
    Streamlit startup threads. Caller-owned connections are never closed here.
    """
    if not isinstance(bind, (Engine, Connection)):
        raise TypeError("ensure_schema requires a SQLAlchemy Engine or Connection.")
    with _MIGRATION_LOCK:
        try:
            if isinstance(bind, Engine):
                with bind.begin() as connection:
                    _ensure(connection)
            elif bind.in_transaction():
                _ensure(bind)
            else:
                with bind.begin():
                    _ensure(bind)
        except SchemaError:
            raise
        except Exception:
            raise SchemaError(
                "Database migration failed. Check database availability and migration permissions, then retry."
            ) from None
