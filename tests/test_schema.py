"""Migration checks against real disposable databases, without cloud access."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, select, text

from briefly.models import Base, Workspace
from briefly.schema import SchemaError, ensure_schema, migration_config


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="briefly-schema-test-")
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "test.db"))

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_fresh_database_migrates_and_repeat_start_preserves_data(self):
        ensure_schema(self.engine)
        with self.engine.begin() as connection:
            self.assertEqual(("0001_initial",), MigrationContext.configure(connection).get_current_heads())
            self.assertEqual(set(Base.metadata.tables) | {"alembic_version"}, set(inspect(connection).get_table_names()))
            connection.execute(Workspace.__table__.insert().values(id="workspace-1", name="Preserved workspace", created_at=datetime(2026, 1, 1)))
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual("Preserved workspace", connection.scalar(select(Workspace.name)))

    def test_unversioned_application_tables_require_reviewed_baseline(self):
        Workspace.__table__.create(self.engine)
        with self.assertRaisesRegex(SchemaError, "no migration history"):
            ensure_schema(self.engine)
        self.assertEqual(["workspaces"], inspect(self.engine).get_table_names())

    def test_unknown_revision_fails_closed_without_rewriting_history(self):
        ensure_schema(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = 'future_version'"))
        with self.assertRaisesRegex(SchemaError, "not supported"):
            ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual("future_version", connection.scalar(text("SELECT version_num FROM alembic_version")))

    def test_column_and_index_drift_are_rejected(self):
        ensure_schema(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE meetings ADD COLUMN accidental_data TEXT"))
            connection.execute(text("DROP INDEX ix_meetings_status"))
        with self.assertRaisesRegex(SchemaError, "schema differs"):
            ensure_schema(self.engine)
        self.assertIn("accidental_data", {column["name"] for column in inspect(self.engine).get_columns("meetings")})

    def test_missing_primary_key_is_rejected(self):
        ensure_schema(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE users"))
            connection.execute(text("""CREATE TABLE users (
                id VARCHAR(36) NOT NULL,
                username VARCHAR(80) NOT NULL,
                email VARCHAR(254) NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                UNIQUE (username),
                UNIQUE (email)
            )"""))
        with self.assertRaisesRegex(SchemaError, "schema differs"):
            ensure_schema(self.engine)

    def test_unrelated_application_tables_are_preserved(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE another_app (id INTEGER PRIMARY KEY, value TEXT)"))
            connection.execute(text("INSERT INTO another_app VALUES (1, 'keep this')"))
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual("keep this", connection.scalar(text("SELECT value FROM another_app")))

    def test_caller_transaction_is_not_committed_or_connection_closed(self):
        ensure_schema(self.engine)
        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(Workspace.__table__.insert().values(id="rollback-me", name="Pending", created_at=datetime(2026, 1, 1)))
            ensure_schema(connection)
            self.assertFalse(connection.closed)
            self.assertTrue(transaction.is_active)
            self.assertEqual("Pending", connection.scalar(select(Workspace.name)))
            transaction.rollback()
        with self.engine.connect() as connection:
            self.assertIsNone(connection.scalar(select(Workspace.name)))

    def test_idle_caller_connection_remains_usable(self):
        with self.engine.connect() as connection:
            ensure_schema(connection)
            self.assertFalse(connection.closed)
            self.assertEqual(1, connection.scalar(text("SELECT 1")))

    def test_migration_paths_do_not_depend_on_working_directory(self):
        original = Path.cwd()
        try:
            os.chdir(self.temp.name)
            ensure_schema(self.engine)
        finally:
            os.chdir(original)
        self.assertIn("meetings", inspect(self.engine).get_table_names())

    def test_parallel_startup_is_serialized(self):
        with ThreadPoolExecutor(max_workers=3) as workers:
            list(workers.map(ensure_schema, [self.engine] * 3))
        with self.engine.connect() as connection:
            self.assertEqual(("0001_initial",), MigrationContext.configure(connection).get_current_heads())

    def test_unexpected_database_errors_do_not_expose_credentials(self):
        with patch("briefly.schema.command.upgrade", side_effect=RuntimeError("postgresql://secret-user:private-password@db")):
            with self.assertRaises(SchemaError) as captured:
                ensure_schema(self.engine)
        self.assertNotIn("private-password", str(captured.exception))
        self.assertIn("Database migration failed", str(captured.exception))

    def test_offline_postgresql_upgrade_has_concrete_frozen_ddl(self):
        output = io.StringIO()
        config = migration_config()
        config.output_buffer = output
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://placeholder:unused@localhost/briefly"}):
            command.upgrade(config, "head", sql=True)
        sql = output.getvalue()
        self.assertIn("CREATE TABLE meetings", sql)
        self.assertIn("upload BYTEA", sql)
        self.assertIn("FOREIGN KEY(meeting_id) REFERENCES meetings (id) ON DELETE CASCADE", sql)
        self.assertIn("0001_initial", sql)
        self.assertNotIn("placeholder", sql)


if __name__ == "__main__":
    unittest.main()
