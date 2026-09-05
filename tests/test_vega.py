import json
import tempfile
import unittest
from pathlib import Path

from library_search.errors import VegaError
from library_search.vega import VegaClient
from tests.fakes import FakeAsyncClientFactory, FakeResponse
from tests.helpers import make_settings

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class VegaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_bibliographic_page_builds_and_parses_current_request(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = make_settings(Path(directory))
            factory = FakeAsyncClientFactory(
                FakeResponse(load_fixture("vega_bibs.json"))
            )
            client = VegaClient(settings, http_client=factory())

            records = await client.fetch_bibliographic_page(
                date_from=2024,
                date_to=2024,
                page_number=3,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].id, "bib-1")
        self.assertEqual(records[0].edition_id, "edition-1")
        self.assertEqual(
            records[0].cover_url,
            "https://example.test/covers/bib-1.jpg",
        )

        call = factory.calls[0]
        self.assertEqual(call.method, "POST")
        self.assertEqual(call.kwargs["json"]["searchText"], "*")
        self.assertEqual(call.kwargs["json"]["materialTypeIds"], ["1"])
        self.assertEqual(call.kwargs["json"]["locationIds"], ["59"])
        self.assertEqual(call.kwargs["json"]["pageNum"], 3)
        self.assertEqual(call.kwargs["json"]["pageSize"], 100)

    async def test_total_pages_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = FakeAsyncClientFactory(FakeResponse({"totalPages": 7}))
            client = VegaClient(
                make_settings(Path(directory)), http_client=factory()
            )
            total_pages = await client.total_bibliographic_pages(1, 1999)

        self.assertEqual(total_pages, 7)

    async def test_fetch_edition_flattens_valid_multi_value_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = FakeAsyncClientFactory(
                FakeResponse(load_fixture("vega_edition.json"))
            )
            client = VegaClient(
                make_settings(Path(directory)), http_client=factory()
            )
            edition = await client.fetch_edition("edition-1")

        self.assertEqual(edition.id, "edition-1")
        self.assertEqual(edition.author, "Chambers, Becky")
        self.assertEqual(edition.item_language, "eng")
        self.assertEqual(
            edition.subjects,
            "Friendship, Space, Science fiction",
        )
        self.assertEqual(
            edition.summary,
            "A character-focused journey through space.",
        )

    async def test_missing_material_tab_is_rejected_at_the_vega_boundary(self):
        payload = {
            "data": [
                {
                    "id": "bib-1",
                    "title": "Title",
                    "publicationDate": "2024",
                    "coverUrl": {},
                    "materialTabs": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            factory = FakeAsyncClientFactory(FakeResponse(payload))
            client = VegaClient(
                make_settings(Path(directory)), http_client=factory()
            )
            with self.assertRaisesRegex(VegaError, "no material tab"):
                await client.fetch_bibliographic_page(
                    date_from=2024,
                    date_to=2024,
                    page_number=0,
                )


if __name__ == "__main__":
    unittest.main()
