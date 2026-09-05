"""Shared test configuration helpers."""

from pathlib import Path

from library_search.config import Settings


def make_settings(
    root: Path,
    *,
    embedding_dimension: int = 1536,
    maximum_query_length: int = 1000,
) -> Settings:
    return Settings(
        project_root=root,
        database_path=root / "test.db",
        log_path=root / "test.log",
        openai_api_key="test-openai-key",
        embedding_dimension=embedding_dimension,
        maximum_query_length=maximum_query_length,
    )
