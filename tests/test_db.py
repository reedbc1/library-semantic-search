import sqlite3
import tempfile
import unittest
from pathlib import Path

from library_search.db import (
    LATEST_SCHEMA_VERSION,
    CatalogRepository,
    database_connection,
    migrate,
    migrate_database,
)
from library_search.errors import MigrationError
from library_search.models import BibliographicRecord, EditionRecord
from tests.helpers import make_settings


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_fresh_database_reaches_latest_schema(self):
        applied = migrate(self.connection)

        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertEqual(applied, (1, 2))
        self.assertEqual(
            self.connection.execute("PRAGMA user_version").fetchone()[0],
            LATEST_SCHEMA_VERSION,
        )
        self.assertTrue({"bibs", "editions", "records", "embeddings"} <= tables)

    def test_legacy_embedding_column_is_migrated(self):
        self.connection.execute("CREATE TABLE embeddings(id, BLOB)")
        self.connection.execute("INSERT INTO embeddings VALUES('bib-1', 'vector')")
        self.connection.commit()

        migrate(self.connection)

        columns = tuple(
            row[1]
            for row in self.connection.execute("PRAGMA table_info(embeddings)")
        )
        row = self.connection.execute(
            "SELECT id, embedding FROM embeddings"
        ).fetchone()
        self.assertEqual(columns, ("id", "embedding"))
        self.assertEqual(row, ("bib-1", "vector"))

    def test_legacy_tables_are_removed_but_vector_tables_are_preserved(self):
        migrate(self.connection, target_version=1)
        for table in (
            "bibs_legacy",
            "editions_legacy",
            "embeddings_legacy",
            "_sqliteai_vector",
            "vector0_embeddings_embedding",
        ):
            self.connection.execute(f"CREATE TABLE {table}(value)")

        applied = migrate(self.connection)

        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertEqual(applied, (2,))
        self.assertFalse(
            {"bibs_legacy", "editions_legacy", "embeddings_legacy"} & tables
        )
        self.assertTrue(
            {"_sqliteai_vector", "vector0_embeddings_embedding"} <= tables
        )

    def test_newer_unknown_schema_is_rejected(self):
        self.connection.execute(
            f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}"
        )

        with self.assertRaisesRegex(MigrationError, "newer than supported"):
            migrate(self.connection)

    def test_failed_migration_rolls_back_schema_changes(self):
        self.connection.execute(
            "CREATE TABLE bibs(id PRIMARY KEY, title, publicationDate, "
            "coverUrl, editionId)"
        )
        self.connection.execute(
            "INSERT INTO bibs VALUES(?, ?, ?, ?, ?)",
            ("bib-1", None, "2024", None, "edition-1"),
        )
        self.connection.commit()

        with self.assertRaisesRegex(MigrationError, "Migration 1"):
            migrate(self.connection)

        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertEqual(
            self.connection.execute("PRAGMA user_version").fetchone()[0], 0
        )
        self.assertEqual(tables, {"bibs"})


class CatalogRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = CatalogRepository(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_bibliographic_sync_parameterizes_single_deletion(self):
        self.connection.execute(
            "INSERT INTO bibs VALUES(?, ?, ?, ?, ?)",
            ("obsolete", "Old", "2020", None, "edition-old"),
        )
        records = [
            BibliographicRecord("new", "New", "2024", None, "edition-new")
        ]

        changes = self.repository.sync_bibliographic_records(records)

        self.assertEqual(changes.to_insert, {"new"})
        self.assertEqual(changes.to_delete, {"obsolete"})
        self.assertEqual(
            self.connection.execute("SELECT id FROM bibs").fetchall(),
            [("new",)],
        )

    def test_rebuild_records_swaps_a_complete_inner_join(self):
        self.repository.sync_bibliographic_records(
            [BibliographicRecord("bib-1", "Title", "2024", None, "edition-1")]
        )
        changes = self.repository.edition_changes()
        self.repository.apply_edition_changes(
            [EditionRecord("edition-1", "Author", "eng", "Space", "Summary")],
            changes,
        )

        count = self.repository.rebuild_records()

        self.assertEqual(count, 1)
        row = self.connection.execute("SELECT * FROM records").fetchone()
        self.assertEqual(
            row,
            (
                "bib-1",
                "Title",
                "Author",
                "2024",
                "eng",
                "Space",
                "Summary",
                None,
            ),
        )

    def test_embedding_input_preserves_current_text_contract(self):
        self.connection.execute(
            "INSERT INTO records VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "bib-1",
                "Title",
                "Author",
                "2024",
                "eng",
                "Space",
                "Summary",
                None,
            ),
        )

        inputs = self.repository.embedding_inputs(["bib-1"])

        self.assertEqual(
            inputs[0].text,
            "title: Title, author: Author, publication date: 2024, "
            "lanugage: eng, subjects: Space, summary: Summary",
        )

    def test_managed_connection_rolls_back_and_closes_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            migrate_database(settings)
            captured = None
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with database_connection(settings, write=True) as connection:
                    captured = connection
                    connection.execute(
                        "INSERT INTO bibs VALUES(?, ?, ?, ?, ?)",
                        ("bib-1", "Title", "2024", None, "edition-1"),
                    )
                    raise RuntimeError("stop")

            with self.assertRaises(sqlite3.ProgrammingError):
                captured.execute("SELECT 1")
            with database_connection(settings) as connection:
                count = connection.execute("SELECT COUNT(*) FROM bibs").fetchone()[0]
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
