"""Command-line entry point for synchronization and database maintenance."""

import argparse
import asyncio
import json

from library_search.config import Settings
from library_search.db import database_inventory, migrate_database
from library_search.sync import configure_logging, synchronize


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync", help="synchronize catalog data and embeddings")
    subparsers.add_parser("migrate", help="apply pending database migrations")
    subparsers.add_parser("database-info", help="print database schema inventory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    require_key = args.command == "sync"
    settings = Settings.from_env(require_openai_api_key=require_key)

    if args.command == "sync":
        configure_logging(settings)
        summary = asyncio.run(synchronize(settings))
        print(summary)
    elif args.command == "migrate":
        print(json.dumps({"applied_migrations": migrate_database(settings)}))
    else:
        print(json.dumps(database_inventory(settings), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
