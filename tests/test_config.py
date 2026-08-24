import tempfile
import unittest
from pathlib import Path

from library_search.config import Settings
from library_search.errors import ConfigurationError


class SettingsTests(unittest.TestCase):
    def test_from_env_resolves_paths_against_the_project_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings.from_env(
                environ={
                    "OPENAI_API_KEY": "test-key",
                    "DATABASE_PATH": "data/catalog.db",
                    "LOG_PATH": "logs/sync.log",
                },
                project_root=root,
                require_openai_api_key=True,
            )

        self.assertEqual(settings.database_path, (root / "data/catalog.db").resolve())
        self.assertEqual(settings.log_path, (root / "logs/sync.log").resolve())

    def test_required_openai_key_is_validated_at_the_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigurationError, "OPENAI_API_KEY"):
                Settings.from_env(
                    environ={},
                    project_root=Path(directory),
                    require_openai_api_key=True,
                )

    def test_non_positive_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigurationError, "vega_page_size"):
                Settings.from_env(
                    environ={"VEGA_PAGE_SIZE": "0"},
                    project_root=Path(directory),
                )


if __name__ == "__main__":
    unittest.main()
