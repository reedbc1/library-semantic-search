"""SQLite connections, schema migrations, and catalog persistence."""

import importlib.resources
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from library_search.config import Settings
from library_search.errors import DatabaseError, MigrationError
from library_search.models import (
    BibliographicRecord,
    ChangeSet,
    EditionRecord,
    EmbeddingInput,
)

LATEST_SCHEMA_VERSION = 2
APPLICATION_TABLES = ("bibs", "editions", "records", "embeddings")
LEGACY_TABLES = ("bibs_legacy", "editions_legacy", "embeddings_legacy")
VECTOR_TABLES = ("_sqliteai_vector", "vector0_embeddings_embedding")
RECORD_COLUMNS = (
    "id",
    "title",
    "author",
    "publicationDate",
    "itemLanguage",
    "subjects",
    "summary",
    "coverUrl",
)

EXPECTED_COLUMNS = {
    "bibs": ("id", "title", "publicationDate", "coverUrl", "editionId"),
    "editions": ("id", "author", "itemLanguage", "subjects", "summary"),
    "records": RECORD_COLUMNS,
    "embeddings": ("id", "embedding"),
}
REQUIRED_VALUE_COLUMNS = {
    "bibs": ("id", "title", "publicationDate", "editionId"),
    "editions": ("id", "author", "itemLanguage", "subjects", "summary"),
    "records": (
        "id",
        "title",
        "author",
        "publicationDate",
        "itemLanguage",
        "subjects",
        "summary",
    ),
    "embeddings": ("id", "embedding"),
}


def _create_bibs_sql(table: str = "bibs") -> str:
    return (
        f"CREATE TABLE {table}("
        "id TEXT PRIMARY KEY NOT NULL, "
        "title TEXT NOT NULL, "
        "publicationDate TEXT NOT NULL, "
        "coverUrl TEXT, "
        "editionId TEXT NOT NULL)"
    )


def _create_editions_sql(table: str = "editions") -> str:
    return (
        f"CREATE TABLE {table}("
        "id TEXT PRIMARY KEY NOT NULL, "
        "author TEXT NOT NULL, "
        "itemLanguage TEXT NOT NULL, "
        "subjects TEXT NOT NULL, "
        "summary TEXT NOT NULL)"
    )


def _create_records_sql(table: str = "records") -> str:
    return (
        f"CREATE TABLE {table}("
        "id TEXT PRIMARY KEY NOT NULL, "
        "title TEXT NOT NULL, "
        "author TEXT NOT NULL, "
        "publicationDate TEXT NOT NULL, "
        "itemLanguage TEXT NOT NULL, "
        "subjects TEXT NOT NULL, "
        "summary TEXT NOT NULL, "
        "coverUrl TEXT)"
    )


def _create_embeddings_sql(table: str = "embeddings") -> str:
    return (
        f"CREATE TABLE {table}("
        "id TEXT PRIMARY KEY NOT NULL, "
        "embedding BLOB NOT NULL)"
    )


def _load_vector_extension(connection: sqlite3.Connection) -> None:
    extension = importlib.resources.files("sqlite_vector.binaries") / "vector"
    connection.enable_load_extension(True)
    try:
        connection.load_extension(str(extension))
    finally:
        connection.enable_load_extension(False)


def connect_database(path: Path | str) -> sqlite3.Connection:
    database_path = Path(path).expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    _load_vector_extension(connection)
    return connection


@contextmanager
def database_connection(
    settings: Settings,
    *,
    write: bool = False,
) -> Iterator[sqlite3.Connection]:
    connection = connect_database(settings.database_path)
    try:
        yield connection
        if write:
            connection.commit()
        elif connection.in_transaction:
            connection.rollback()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _column_names(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    )


def _validate_application_schema(connection: sqlite3.Connection) -> None:
    for table, expected_columns in EXPECTED_COLUMNS.items():
        if not _table_exists(connection, table):
            raise MigrationError(f"Required table is missing: {table}")
        actual_columns = _column_names(connection, table)
        if actual_columns != expected_columns:
            raise MigrationError(
                f"Unexpected columns for {table}: "
                f"expected {expected_columns}, found {actual_columns}"
            )
        table_info = connection.execute(f"PRAGMA table_info({table})").fetchall()
        id_column = next(column for column in table_info if column[1] == "id")
        if id_column[5] != 1:
            raise MigrationError(f"Table {table} must have id as its primary key")


def _validate_application_data(connection: sqlite3.Connection) -> None:
    for table, columns in REQUIRED_VALUE_COLUMNS.items():
        predicate = " OR ".join(f"{column} IS NULL" for column in columns)
        null_count = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {predicate}"
        ).fetchone()[0]
        if null_count:
            raise MigrationError(
                f"Table {table} has {null_count} rows with missing required values"
            )


def _migration_1_create_or_adopt_schema(connection: sqlite3.Connection) -> None:
    table_builders = {
        "bibs": _create_bibs_sql,
        "editions": _create_editions_sql,
        "records": _create_records_sql,
    }
    for table, builder in table_builders.items():
        if not _table_exists(connection, table):
            connection.execute(builder())

    if not _table_exists(connection, "embeddings"):
        connection.execute(_create_embeddings_sql())
    elif _column_names(connection, "embeddings") == ("id", "BLOB"):
        connection.execute("DROP TABLE IF EXISTS _migration_embeddings")
        connection.execute(
            "ALTER TABLE embeddings RENAME TO _migration_embeddings"
        )
        connection.execute(_create_embeddings_sql())
        connection.execute(
            "INSERT INTO embeddings(id, embedding) "
            "SELECT id, BLOB FROM _migration_embeddings"
        )
        connection.execute("DROP TABLE _migration_embeddings")

    _validate_application_schema(connection)
    _validate_application_data(connection)


def _migration_2_remove_legacy_tables(connection: sqlite3.Connection) -> None:
    for table in LEGACY_TABLES:
        connection.execute(f"DROP TABLE IF EXISTS {table}")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Any


MIGRATIONS = (
    Migration(1, "create or adopt application schema", _migration_1_create_or_adopt_schema),
    Migration(2, "remove verified legacy migration tables", _migration_2_remove_legacy_tables),
)


def migrate(
    connection: sqlite3.Connection,
    *,
    target_version: int = LATEST_SCHEMA_VERSION,
) -> tuple[int, ...]:
    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version > LATEST_SCHEMA_VERSION:
        raise MigrationError(
            f"Database schema version {current_version} is newer than supported "
            f"version {LATEST_SCHEMA_VERSION}"
        )
    if target_version > LATEST_SCHEMA_VERSION or target_version < current_version:
        raise MigrationError(f"Invalid migration target: {target_version}")

    applied: list[int] = []
    for migration in MIGRATIONS:
        if current_version < migration.version <= target_version:
            try:
                connection.execute("BEGIN IMMEDIATE")
                migration.apply(connection)
                connection.execute(f"PRAGMA user_version = {migration.version}")
                connection.commit()
            except Exception as error:
                connection.rollback()
                raise MigrationError(
                    f"Migration {migration.version} ({migration.name}) failed"
                ) from error
            applied.append(migration.version)
            current_version = migration.version

    _validate_application_schema(connection)
    _validate_application_data(connection)
    return tuple(applied)


def migrate_database(settings: Settings) -> tuple[int, ...]:
    with database_connection(settings, write=True) as connection:
        return migrate(connection)


def require_current_schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != LATEST_SCHEMA_VERSION:
        raise MigrationError(
            f"Database schema version {version} is not the required version "
            f"{LATEST_SCHEMA_VERSION}; run `python -m library_search migrate`"
        )
    _validate_application_schema(connection)


def database_inventory(settings: Settings) -> dict[str, Any]:
    with database_connection(settings) as connection:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' ORDER BY name"
            )
        )
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in APPLICATION_TABLES
            if table in tables
        }
        return {
            "database": str(settings.database_path),
            "schema_version": connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0],
            "integrity_check": connection.execute(
                "PRAGMA quick_check"
            ).fetchone()[0],
            "tables": tables,
            "counts": counts,
        }


def legacy_table_inventory(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in LEGACY_TABLES
        if _table_exists(connection, table)
    }


def _changes(source_ids: set[str], stored_ids: set[str]) -> ChangeSet:
    return ChangeSet(
        to_insert=frozenset(source_ids - stored_ids),
        to_delete=frozenset(stored_ids - source_ids),
        unchanged=frozenset(source_ids & stored_ids),
    )


def _delete_ids(
    connection: sqlite3.Connection, table: str, ids: Sequence[str]
) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    connection.execute(
        f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(ids)
    )


class CatalogRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def sync_bibliographic_records(
        self, records: Sequence[BibliographicRecord]
    ) -> ChangeSet:
        records_by_id = {record.id: record for record in records}
        stored_ids = {
            row[0] for row in self.connection.execute("SELECT id FROM bibs")
        }
        changes = _changes(set(records_by_id), stored_ids)

        _delete_ids(self.connection, "bibs", sorted(changes.to_delete))
        self.connection.executemany(
            "INSERT INTO bibs(id, title, publicationDate, coverUrl, editionId) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                records_by_id[record_id].as_database_tuple()
                for record_id in sorted(changes.to_insert)
            ),
        )
        return changes

    def edition_changes(self) -> ChangeSet:
        source_ids = {
            row[0]
            for row in self.connection.execute(
                "SELECT editionId FROM bibs WHERE editionId IS NOT NULL"
            )
        }
        stored_ids = {
            row[0] for row in self.connection.execute("SELECT id FROM editions")
        }
        return _changes(source_ids, stored_ids)

    def apply_edition_changes(
        self, records: Sequence[EditionRecord], changes: ChangeSet
    ) -> None:
        records_by_id = {record.id: record for record in records}
        missing = set(changes.to_insert) - set(records_by_id)
        if missing:
            raise DatabaseError(
                f"Fetched edition records are missing IDs: {sorted(missing)}"
            )

        _delete_ids(self.connection, "editions", sorted(changes.to_delete))
        self.connection.executemany(
            "INSERT INTO editions(id, author, itemLanguage, subjects, summary) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                records_by_id[record_id].as_database_tuple()
                for record_id in sorted(changes.to_insert)
            ),
        )

    def rebuild_records(self) -> int:
        self.connection.execute("DROP TABLE IF EXISTS records_new")
        self.connection.execute(_create_records_sql("records_new"))
        self.connection.execute(
            "INSERT INTO records_new "
            "SELECT b.id, b.title, e.author, b.publicationDate, "
            "e.itemLanguage, e.subjects, e.summary, b.coverUrl "
            "FROM bibs AS b INNER JOIN editions AS e ON e.id = b.editionId"
        )
        count = self.connection.execute(
            "SELECT COUNT(*) FROM records_new"
        ).fetchone()[0]
        self.connection.execute("DROP TABLE records")
        self.connection.execute("ALTER TABLE records_new RENAME TO records")
        return count

    def embedding_changes(self) -> ChangeSet:
        source_ids = {
            row[0] for row in self.connection.execute("SELECT id FROM records")
        }
        stored_ids = {
            row[0] for row in self.connection.execute("SELECT id FROM embeddings")
        }
        return _changes(source_ids, stored_ids)

    def embedding_inputs(self, ids: Sequence[str]) -> list[EmbeddingInput]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.connection.execute(
            "SELECT id, title, author, publicationDate, itemLanguage, "
            f"subjects, summary FROM records WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
        return [
            EmbeddingInput(
                id=row[0],
                text=(
                    f"title: {row[1]}, author: {row[2]}, "
                    f"publication date: {row[3]}, lanugage: {row[4]}, "
                    f"subjects: {row[5]}, summary: {row[6]}"
                ),
            )
            for row in rows
        ]

    def apply_embedding_changes(
        self,
        embeddings: Sequence[tuple[str, str]],
        changes: ChangeSet,
    ) -> None:
        embedded_ids = {record_id for record_id, _ in embeddings}
        missing = set(changes.to_insert) - embedded_ids
        if missing:
            raise DatabaseError(f"Embeddings are missing IDs: {sorted(missing)}")

        _delete_ids(self.connection, "embeddings", sorted(changes.to_delete))
        self.connection.executemany(
            "INSERT INTO embeddings(id, embedding) VALUES(?, vector_as_f32(?))",
            embeddings,
        )
