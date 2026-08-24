import math
import tempfile
import unittest
from pathlib import Path

from library_search.embeddings import (
    create_query_embedding,
    create_record_embedding,
    validate_embedding,
)
from library_search.errors import EmbeddingError
from library_search.models import EmbeddingInput
from tests.fakes import FakeAsyncOpenAIClient, FakeSyncOpenAIClient
from tests.helpers import make_settings


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.settings = make_settings(
            Path(self.temporary_directory.name), embedding_dimension=3
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_query_embedding_uses_configured_model_and_dimension(self):
        client = FakeSyncOpenAIClient([0.1, 0.2, 0.3])

        embedding = create_query_embedding(client, "quiet fiction", self.settings)

        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.assertEqual(
            client.embeddings.calls,
            [
                {
                    "input": "quiet fiction",
                    "model": "text-embedding-3-small",
                }
            ],
        )

    def test_wrong_dimension_is_rejected(self):
        with self.assertRaisesRegex(EmbeddingError, "dimension"):
            validate_embedding([0.1, 0.2], self.settings)

    def test_non_finite_component_is_rejected(self):
        with self.assertRaisesRegex(EmbeddingError, "non-finite"):
            validate_embedding([0.1, math.inf, 0.3], self.settings)


class AsyncEmbeddingTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_embedding_is_validated_and_stringified(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory), embedding_dimension=3)
            client = FakeAsyncOpenAIClient([0.25, 0.5, 0.75])
            result = await create_record_embedding(
                client,
                EmbeddingInput("bib-1", "record text"),
                settings,
            )

        self.assertEqual(result, ("bib-1", "[0.25, 0.5, 0.75]"))


if __name__ == "__main__":
    unittest.main()
