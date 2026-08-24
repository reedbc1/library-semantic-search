import importlib.resources
import sqlite3
import unittest
from unittest.mock import patch

import sync_db
from tests.fakes import FakeAsyncOpenAIClient, FakeSyncOpenAIClient


class SyncDatabaseCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()

    def tearDown(self):
        self.connection.close()

    def test_ensure_embeddings_table_creates_current_columns(self):
        sync_db.ensure_embeddings_table(self.connection, self.cursor)

        columns = self.cursor.execute(
            "PRAGMA table_info(embeddings)"
        ).fetchall()
        self.assertEqual([column[1] for column in columns], ["id", "embedding"])

    def test_bibs_inserts_and_deletes_by_id_without_updating_existing_ids(self):
        self.cursor.execute(
            "CREATE TABLE bibs(id PRIMARY KEY, title, publicationDate, "
            "coverUrl, editionId)"
        )
        self.cursor.executemany(
            "INSERT INTO bibs VALUES(?, ?, ?, ?, ?)",
            [
                ("stable", "Original Title", "2020", "old.jpg", "edition-1"),
                ("obsolete-1", "Old One", "2010", "one.jpg", "edition-2"),
                ("obsolete-2", "Old Two", "2011", "two.jpg", "edition-3"),
            ],
        )

        async def fake_fetch_all_bibs():
            return (
                [
                    (
                        "stable",
                        "Changed Upstream Title",
                        "2020",
                        "new.jpg",
                        "edition-1",
                    ),
                    ("new", "New Title", "2024", "new.jpg", "edition-4"),
                ],
                {"stable", "new"},
            )

        with patch.object(
            sync_db.fetch_items,
            "fetch_all_bibs",
            new=fake_fetch_all_bibs,
        ):
            sync_db.bibs(self.connection, self.cursor)

        rows = self.cursor.execute(
            "SELECT id, title FROM bibs ORDER BY id"
        ).fetchall()
        self.assertEqual(
            rows,
            [("new", "New Title"), ("stable", "Original Title")],
        )

    def test_ensure_embeddings_table_migrates_legacy_blob_column(self):
        self.cursor.execute("CREATE TABLE embeddings(id, BLOB)")
        self.cursor.execute("INSERT INTO embeddings VALUES('bib-1', 'vector')")

        sync_db.ensure_embeddings_table(self.connection, self.cursor)

        columns = self.cursor.execute(
            "PRAGMA table_info(embeddings)"
        ).fetchall()
        rows = self.cursor.execute("SELECT id, embedding FROM embeddings").fetchall()
        legacy_table = self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE name = 'embeddings_legacy'"
        ).fetchone()
        self.assertEqual([column[1] for column in columns], ["id", "embedding"])
        self.assertEqual(rows, [("bib-1", "vector")])
        self.assertIsNone(legacy_table)

    def test_join_tables_rebuilds_the_current_flattened_record_shape(self):
        self.cursor.execute(
            "CREATE TABLE bibs(id PRIMARY KEY, title, publicationDate, "
            "coverUrl, editionId)"
        )
        self.cursor.execute(
            "CREATE TABLE editions(id PRIMARY KEY, author, itemLanguage, "
            "subjects, summary)"
        )
        self.cursor.execute(
            "INSERT INTO bibs VALUES(?, ?, ?, ?, ?)",
            ("bib-1", "Title", "2024", "cover.jpg", "edition-1"),
        )
        self.cursor.execute(
            "INSERT INTO editions VALUES(?, ?, ?, ?, ?)",
            ("edition-1", "Author", "eng", "Subject", "Summary"),
        )

        sync_db.join_tables(self.connection, self.cursor)

        row = self.cursor.execute("SELECT * FROM records").fetchone()
        self.assertEqual(
            row,
            (
                "bib-1",
                "Title",
                "Author",
                "2024",
                "eng",
                "Subject",
                "Summary",
                "cover.jpg",
            ),
        )

    def test_get_collection_preserves_current_labeled_embedding_text(self):
        self.cursor.execute(
            "CREATE TABLE records(id PRIMARY KEY, title, author, "
            "publicationDate, itemLanguage, subjects, summary, coverUrl)"
        )
        records = [
            (
                "bib-1",
                "Title One",
                "Author One",
                "2024",
                "eng",
                "Space",
                "Summary One",
                "one.jpg",
            ),
            (
                "bib-2",
                "Title Two",
                "Author Two",
                "2023",
                "spa",
                "Travel",
                "Summary Two",
                "two.jpg",
            ),
        ]
        self.cursor.executemany("INSERT INTO records VALUES(?, ?, ?, ?, ?, ?, ?, ?)", records)

        collection = dict(
            sync_db.get_collection(
                self.connection, self.cursor, {"bib-1", "bib-2"}
            )
        )

        self.assertEqual(
            collection["bib-1"],
            "title: Title One, author: Author One, publication date: 2024, "
            "lanugage: eng, subjects: Space, summary: Summary One",
        )
        self.assertEqual(
            collection["bib-2"],
            "title: Title Two, author: Author Two, publication date: 2023, "
            "lanugage: spa, subjects: Travel, summary: Summary Two",
        )

    def test_sql_to_json_uses_record_columns_and_discards_distance(self):
        self.cursor.execute(
            "CREATE TABLE records(id PRIMARY KEY, title, author, "
            "publicationDate, itemLanguage, subjects, summary, coverUrl)"
        )
        row_with_distance = (
            "bib-1",
            "Title",
            "Author",
            "2024",
            "eng",
            "Subject",
            "Summary",
            "cover.jpg",
            0.125,
        )

        with patch("builtins.print"):
            result = sync_db.sql_to_json(
                self.connection, self.cursor, [row_with_distance]
            )

        self.assertEqual(
            result,
            [
                {
                    "id": "bib-1",
                    "title": "Title",
                    "author": "Author",
                    "publicationDate": "2024",
                    "itemLanguage": "eng",
                    "subjects": "Subject",
                    "summary": "Summary",
                    "coverUrl": "cover.jpg",
                }
            ],
        )

    def test_embed_query_uses_the_current_model(self):
        client = FakeSyncOpenAIClient([0.1, 0.2, 0.3])

        with patch.object(sync_db, "OpenAI", return_value=client):
            embedding = sync_db.embed_query("quiet science fiction")

        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.assertEqual(
            client.embeddings.calls,
            [
                {
                    "input": "quiet science fiction",
                    "model": "text-embedding-3-small",
                }
            ],
        )


class AsyncEmbeddingCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_embedding_stringifies_the_current_vector(self):
        client = FakeAsyncOpenAIClient([0.25, 0.5])

        result = await sync_db.create_embedding(client, "bib-1", "record text")

        self.assertEqual(result, ("bib-1", "[0.25, 0.5]"))
        self.assertEqual(
            client.embeddings.calls,
            [
                {
                    "input": "record text",
                    "model": "text-embedding-3-small",
                }
            ],
        )


class VectorSearchCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        extension = importlib.resources.files("sqlite_vector.binaries") / "vector"
        self.connection.enable_load_extension(True)
        self.connection.load_extension(str(extension))
        self.connection.enable_load_extension(False)

        self.cursor.execute(
            "CREATE TABLE records(id PRIMARY KEY, title, author, "
            "publicationDate, itemLanguage, subjects, summary, coverUrl)"
        )
        self.cursor.executemany(
            "INSERT INTO records VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("exact", "Exact", "Author", "2024", "eng", "S", "S", "e"),
                ("near", "Near", "Author", "2024", "eng", "S", "S", "n"),
                ("far", "Far", "Author", "2024", "eng", "S", "S", "f"),
            ],
        )

        exact = [0.0] * 1536
        exact[0] = 1.0
        near = [0.0] * 1536
        near[0] = 0.8
        near[1] = 0.2
        far = [0.0] * 1536
        far[0] = -1.0
        sync_db.embeddings_table(
            self.connection,
            self.cursor,
            [
                ("exact", str(exact)),
                ("near", str(near)),
                ("far", str(far)),
            ],
        )
        self.query_embedding = exact

    def tearDown(self):
        self.connection.close()

    def test_sim_search_orders_representative_vectors_by_distance(self):
        with (
            patch.object(
                sync_db, "embed_query", return_value=self.query_embedding
            ),
            patch("builtins.print"),
        ):
            rows = sync_db.sim_search(
                self.connection, self.cursor, "representative query"
            )

        self.assertEqual([row[0] for row in rows], ["exact", "near", "far"])


if __name__ == "__main__":
    unittest.main()
