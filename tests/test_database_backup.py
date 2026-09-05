import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.database_backup import (
    backup_database,
    restore_database,
    verify_database,
)


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source.db"

        with closing(sqlite3.connect(self.source)) as connection:
            connection.execute("PRAGMA user_version = 7")
            connection.execute("CREATE TABLE example(id PRIMARY KEY, value)")
            connection.executemany(
                "INSERT INTO example VALUES(?, ?)",
                [("one", "First"), ("two", "Second")],
            )
            connection.commit()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_backup_verify_and_restore_round_trip(self):
        backup = self.root / "backups" / "source-backup.db"
        restored = self.root / "restored.db"

        backup_report = backup_database(self.source, backup)
        verification_report = verify_database(backup)
        restore_report = restore_database(backup, restored)

        self.assertEqual(backup_report["integrity_check"], "ok")
        self.assertEqual(verification_report["table_names"], ("example",))
        self.assertEqual(verification_report["user_version"], 7)
        self.assertEqual(restore_report["integrity_check"], "ok")

        with closing(sqlite3.connect(restored)) as connection:
            rows = connection.execute(
                "SELECT id, value FROM example ORDER BY id"
            ).fetchall()
        self.assertEqual(rows, [("one", "First"), ("two", "Second")])

    def test_backup_refuses_to_overwrite_an_existing_file(self):
        destination = self.root / "existing.db"
        destination.touch()

        with self.assertRaises(FileExistsError):
            backup_database(self.source, destination)

    def test_restore_refuses_to_overwrite_an_existing_database(self):
        backup = self.root / "source-backup.db"
        destination = self.root / "existing.db"
        backup_database(self.source, backup)
        destination.touch()

        with self.assertRaises(FileExistsError):
            restore_database(backup, destination)

    def test_source_cannot_be_its_own_backup(self):
        with self.assertRaises(ValueError):
            backup_database(self.source, self.source)


if __name__ == "__main__":
    unittest.main()
