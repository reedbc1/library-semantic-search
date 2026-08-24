import tomllib
import unittest
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).parent.parent


class ProjectConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configuration = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

    def test_requirements_mirror_exact_project_dependencies(self):
        project_dependencies = self.configuration["project"]["dependencies"]
        requirements = [
            line
            for line in (ROOT / "requirements.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line and not line.startswith("#")
        ]

        self.assertEqual(requirements, project_dependencies)
        self.assertTrue(all("==" in dependency for dependency in requirements))

    def test_installed_direct_dependencies_match_the_pins(self):
        dependencies = self.configuration["project"]["dependencies"]
        development_dependencies = self.configuration["project"][
            "optional-dependencies"
        ]["dev"]

        for requirement in dependencies + development_dependencies:
            package, expected_version = requirement.split("==", maxsplit=1)
            with self.subTest(package=package):
                self.assertEqual(version(package), expected_version)

    def test_supported_python_and_ruff_target_are_consistent(self):
        self.assertEqual(
            self.configuration["project"]["requires-python"],
            ">=3.13,<3.14",
        )
        self.assertEqual(self.configuration["tool"]["ruff"]["target-version"], "py313")


if __name__ == "__main__":
    unittest.main()
