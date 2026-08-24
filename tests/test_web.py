import unittest
from unittest.mock import patch

from flaskr import app


class WebCharacterizationTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_home_page_and_packaged_stylesheet_are_available(self):
        home_response = self.client.get("/")
        css_response = self.client.get("/static/style.css")
        self.addCleanup(home_response.close)
        self.addCleanup(css_response.close)

        self.assertEqual(home_response.status_code, 200)
        self.assertIn(b"WR Semantic Search", home_response.data)
        self.assertEqual(css_response.status_code, 200)
        self.assertIn(b".result-card", css_response.data)

    def test_search_passes_query_through_and_renders_current_record_fields(self):
        connection = object()
        cursor = object()
        rendered_records = [
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

        with (
            patch(
                "flaskr.sync_db.create_con", return_value=(connection, cursor)
            ) as create_connection,
            patch("flaskr.sync_db.sim_search", return_value=[("raw",)]) as search,
            patch(
                "flaskr.sync_db.sql_to_json", return_value=rendered_records
            ) as convert,
        ):
            response = self.client.get("/search?query=space+opera")
            self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Title", response.data)
        self.assertIn(b"Test Author", response.data)
        create_connection.assert_called_once_with()
        search.assert_called_once_with(
            connection, cursor, user_query="space opera"
        )
        convert.assert_called_once_with(connection, cursor, [("raw",)])

    def test_missing_search_query_uses_the_current_flask_default(self):
        with (
            patch("flaskr.sync_db.create_con", return_value=(object(), object())),
            patch("flaskr.sync_db.sim_search", return_value=[]) as search,
            patch("flaskr.sync_db.sql_to_json", return_value=[]),
        ):
            response = self.client.get("/search")
            self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(search.call_args.kwargs["user_query"], "Flask")


if __name__ == "__main__":
    unittest.main()
