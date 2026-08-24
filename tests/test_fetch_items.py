import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import fetch_items
from tests.fakes import FakeAsyncClientFactory, FakeResponse

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FetchItemsCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_bibs_builds_current_request_and_parses_first_edition(self):
        factory = FakeAsyncClientFactory(
            FakeResponse(load_fixture("vega_bibs.json"))
        )

        with patch.object(fetch_items.httpx, "AsyncClient", factory):
            records, ids = await fetch_items.fetch_bibs(
                asyncio.Semaphore(5),
                dateFrom=2024,
                dateTo=2024,
                pageNum=3,
            )

        self.assertEqual(
            records,
            [
                (
                    "bib-1",
                    "The Long Way to a Small, Angry Planet",
                    "2014",
                    "https://example.test/covers/bib-1.jpg",
                    "edition-1",
                )
            ],
        )
        self.assertEqual(ids, {"bib-1"})
        self.assertEqual(factory.constructor_kwargs, [{"timeout": None}])

        call = factory.calls[0]
        self.assertEqual(call.method, "POST")
        self.assertTrue(call.url.endswith("/search-result/search/format-groups"))
        self.assertEqual(call.kwargs["json"]["searchText"], "*")
        self.assertEqual(call.kwargs["json"]["materialTypeIds"], ["1"])
        self.assertEqual(call.kwargs["json"]["locationIds"], ["59"])
        self.assertEqual(call.kwargs["json"]["pageNum"], 3)
        self.assertEqual(call.kwargs["json"]["pageSize"], 100)
        self.assertEqual(call.kwargs["json"]["dateFrom"], 2024)
        self.assertEqual(call.kwargs["json"]["dateTo"], 2024)

    async def test_fetch_bibs_can_return_the_page_count(self):
        factory = FakeAsyncClientFactory(FakeResponse({"totalPages": 7}))

        with patch.object(fetch_items.httpx, "AsyncClient", factory):
            total_pages = await fetch_items.fetch_bibs(
                asyncio.Semaphore(5),
                dateFrom=1,
                dateTo=1999,
                get_pages=True,
            )

        self.assertEqual(total_pages, 7)

    async def test_fetch_edition_flattens_current_multi_value_fields(self):
        factory = FakeAsyncClientFactory(
            FakeResponse(load_fixture("vega_edition.json"))
        )

        with patch.object(fetch_items.httpx, "AsyncClient", factory):
            edition = await fetch_items.fetch_edition(
                "edition-1", asyncio.Semaphore(5)
            )

        self.assertEqual(
            edition,
            (
                "edition-1",
                "Chambers, Becky",
                "eng",
                "Friendship, Space, Science fiction",
                "A character-focused journey through space.",
            ),
        )
        self.assertEqual(factory.calls[0].method, "GET")
        self.assertTrue(factory.calls[0].url.endswith("/editions/edition-1"))

    def test_get_lang_preserves_current_partial_mapping_behavior(self):
        self.assertEqual(fetch_items.get_lang(" ENG "), "English")
        self.assertEqual(fetch_items.get_lang("not-mapped"), "Undefined")


if __name__ == "__main__":
    unittest.main()
