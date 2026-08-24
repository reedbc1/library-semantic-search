import tempfile
import unittest
from pathlib import Path

from library_search.db import (
    CatalogRepository,
    database_connection,
    migrate_database,
)
from library_search.errors import InputValidationError
from library_search.models import ChangeSet
from library_search.search import search_catalog, validate_query
from tests.fakes import FakeSyncOpenAIClient
from tests.helpers import make_settings


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.settings = make_settings(
            Path(self.temporary_directory.name), embedding_dimension=3
        )
        migrate_database(self.settings)
        with database_connection(self.settings, write=True) as connection:
            connection.executemany(
                "INSERT INTO records VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("exact", "Exact", "A", "2024", "eng", "S", "S", None),
                    ("near", "Near", "A", "2024", "eng", "S", "S", None),
                    ("far", "Far", "A", "2024", "eng", "S", "S", None),
                ],
            )
            repository = CatalogRepository(connection)
            repository.apply_embedding_changes(
                [
                    ("exact", "[1.0, 0.0, 0.0]"),
                    ("near", "[0.8, 0.2, 0.0]"),
                    ("far", "[-1.0, 0.0, 0.0]"),
                ],
                ChangeSet(
                    to_insert=frozenset({"exact", "near", "far"}),
                    to_delete=frozenset(),
                    unchanged=frozenset(),
                ),
            )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_real_vector_search_returns_current_record_shape_in_distance_order(self):
        client = FakeSyncOpenAIClient([1.0, 0.0, 0.0])

        records = search_catalog(
            self.settings,
            "  representative query  ",
            openai_client=client,
        )

        self.assertEqual([record["id"] for record in records], ["exact", "near", "far"])
        self.assertNotIn("distance", records[0])
        self.assertEqual(
            client.embeddings.calls[0]["input"], "representative query"
        )

    def test_query_boundary_rejects_missing_blank_and_oversized_values(self):
        with self.assertRaises(InputValidationError):
            validate_query(None, self.settings)
        with self.assertRaises(InputValidationError):
            validate_query("   ", self.settings)

        limited = make_settings(
            Path(self.temporary_directory.name), maximum_query_length=3
        )
        with self.assertRaises(InputValidationError):
            validate_query("four", limited)


if __name__ == "__main__":
    unittest.main()
