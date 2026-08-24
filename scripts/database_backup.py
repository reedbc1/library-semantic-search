"""Create, verify, and restore consistent SQLite database copies."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def _require_file(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{description} does not exist: {resolved}")
    return resolved


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def verify_database(path: Path | str) -> dict[str, Any]:
    """Verify SQLite integrity and return a small, printable inventory."""
    database = _require_file(Path(path), "Database")

    with closing(_connect_read_only(database)) as connection:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        integrity_messages = tuple(row[0] for row in integrity_rows)
        if integrity_messages != ("ok",):
            messages = "; ".join(integrity_messages)
            raise sqlite3.DatabaseError(
                f"Integrity check failed for {database}: {messages}"
            )

        table_names = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' ORDER BY name"
            )
        )
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    return {
        "database": str(database),
        "integrity_check": "ok",
        "table_names": table_names,
        "user_version": user_version,
    }


def _copy_database(source: Path | str, destination: Path | str) -> dict[str, Any]:
    source_path = _require_file(Path(source), "Source database")
    destination_path = Path(destination).expanduser().resolve()

    if source_path == destination_path:
        raise ValueError("Source and destination must be different files")
    if destination_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing destination: {destination_path}"
        )

    destination_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with closing(_connect_read_only(source_path)) as source_connection:
            with closing(sqlite3.connect(destination_path)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.commit()
        return verify_database(destination_path)
    except Exception:
        if destination_path.exists():
            destination_path.unlink()
        raise


def backup_database(source: Path | str, destination: Path | str) -> dict[str, Any]:
    """Create and verify a new SQLite backup without overwriting files."""
    verify_database(source)
    return _copy_database(source, destination)


def restore_database(backup: Path | str, destination: Path | str) -> dict[str, Any]:
    """Restore a verified backup to a destination that must not already exist."""
    verify_database(backup)
    return _copy_database(backup, destination)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="verify a database")
    verify_parser.add_argument("database", type=Path)

    backup_parser = subparsers.add_parser("backup", help="create a backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("destination", type=Path)

    restore_parser = subparsers.add_parser("restore", help="restore a backup")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("destination", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "verify":
        report = verify_database(args.database)
    elif args.command == "backup":
        report = backup_database(args.source, args.destination)
    else:
        report = restore_database(args.backup, args.destination)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
