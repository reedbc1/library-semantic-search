import tempfile
import unittest
from pathlib import Path

from library_search.db import database_connection, migrate_database
from library_search.models import BibliographicRecord, EditionRecord
from library_search.sync import synchronize
from tests.fakes import FakeAsyncOpenAIClient
from tests.helpers import make_settings


class FakeVegaClient:
    def __init__(self):
        self.bibliographic_calls = 0
        self.edition_calls: list[tuple[str, ...]] = []

    async def fetch_all_bibliographic_records(self):
        self.bibliographic_calls += 1
        return [
            BibliographicRecord(
                "bib-1", "Title", "2024", "cover.jpg", "edition-1"
            )
        ]

    async def fetch_editions(self, edition_ids):
        self.edition_calls.append(tuple(edition_ids))
        return [
            EditionRecord(
                edition_id,
                "Author",
                "eng",
                "Space",
                "Summary",
            )
            for edition_id in edition_ids
        ]


class SynchronizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_sync_uses_injected_clients_and_reconciles_all_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory), embedding_dimension=3)
            migrate_database(settings)
            vega = FakeVegaClient()
            embeddings = FakeAsyncOpenAIClient([1.0, 0.0, 0.0])

            first_summary = await synchronize(
                settings,
                vega_client=vega,
                embedding_client=embeddings,
            )
            second_summary = await synchronize(
                settings,
                vega_client=vega,
                embedding_client=embeddings,
            )

            with database_connection(settings) as connection:
                counts = {
                    table: connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    for table in ("bibs", "editions", "records", "embeddings")
                }
                schema_version = connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]

        self.assertEqual(counts, {table: 1 for table in counts})
        self.assertEqual(schema_version, 2)
        self.assertEqual(first_summary.bibliographic.counts["insert"], 1)
        self.assertEqual(first_summary.editions.counts["insert"], 1)
        self.assertEqual(first_summary.embeddings.counts["insert"], 1)
        self.assertEqual(second_summary.bibliographic.counts["unchanged"], 1)
        self.assertEqual(second_summary.editions.counts["unchanged"], 1)
        self.assertEqual(second_summary.embeddings.counts["unchanged"], 1)
        self.assertEqual(vega.edition_calls, [("edition-1",)])
        self.assertEqual(len(embeddings.embeddings.calls), 1)


if __name__ == "__main__":
    unittest.main()
