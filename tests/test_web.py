import tempfile
import unittest
from pathlib import Path

from library_search.errors import SearchError
from library_search.search import validate_query
from library_search.web import create_app
from tests.helpers import make_settings


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.settings = make_settings(Path(self.temporary_directory.name))
        self.queries: list[str] = []

        def fake_search(settings, query):
            normalized = validate_query(query, settings)
            self.queries.append(normalized)
            return [
                {
                    "id": "bib-1",
                    "title": "Test Title",
                    "author": "Test Author",
                    "publicationDate": "2024",
                    "itemLanguage": "eng",
                    "subjects": "Space",
                    "summary": "Test Summary",
                    "coverUrl": "https://example.test/cover.jpg",
                }
            ]

        self.application = create_app(
            self.settings,
            search_function=fake_search,
        )
        self.application.config.update(TESTING=True)
        self.client = self.application.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_home_page_and_packaged_stylesheet_are_available(self):
        home_response = self.client.get("/")
        css_response = self.client.get("/static/style.css")
        self.addCleanup(home_response.close)
        self.addCleanup(css_response.close)

        self.assertEqual(home_response.status_code, 200)
        self.assertIn(b"WR Semantic Search", home_response.data)
        self.assertEqual(css_response.status_code, 200)
        self.assertIn(b".result-card", css_response.data)

    def test_search_validates_normalizes_and_renders_records(self):
        response = self.client.get("/search?query=+space+opera+")
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.queries, ["space opera"])
        self.assertIn(b"Test Title", response.data)

    def test_missing_and_blank_queries_return_bad_request(self):
        missing_response = self.client.get("/search")
        blank_response = self.client.get("/search?query=+++")
        self.addCleanup(missing_response.close)
        self.addCleanup(blank_response.close)

        self.assertEqual(missing_response.status_code, 400)
        self.assertEqual(blank_response.status_code, 400)

    def test_application_failure_returns_service_unavailable(self):
        def failing_search(settings, query):
            raise SearchError("failed")

        application = create_app(
            self.settings,
            search_function=failing_search,
        )
        application.config.update(TESTING=True)

        with self.assertLogs("library_search.web", level="ERROR"):
            response = application.test_client().get("/search?query=valid")
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"failed", response.data)


if __name__ == "__main__":
    unittest.main()
