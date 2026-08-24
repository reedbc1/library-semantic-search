"""Asynchronous catalog synchronization orchestration."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from library_search.config import Settings
from library_search.db import (
    CatalogRepository,
    database_connection,
    require_current_schema,
)
from library_search.embeddings import create_record_embeddings
from library_search.models import ChangeSet
from library_search.search import prepare_vector_index
from library_search.vega import VegaClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncSummary:
    bibliographic: ChangeSet
    editions: ChangeSet
    embeddings: ChangeSet
    record_count: int


def configure_logging(settings: Settings) -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        encoding="utf-8",
        level=getattr(logging, settings.log_level, logging.INFO),
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.log_path),
        ],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _synchronize_with_vega(
    settings: Settings,
    vega_client: VegaClient,
    *,
    embedding_client: Any | None,
) -> SyncSummary:
    with database_connection(settings) as connection:
        require_current_schema(connection)

    logger.info("fetching bibliographic records")
    bibliographic_records = await vega_client.fetch_all_bibliographic_records()
    with database_connection(settings, write=True) as connection:
        repository = CatalogRepository(connection)
        bibliographic_changes = repository.sync_bibliographic_records(
            bibliographic_records
        )
    logger.info("bibliographic changes: %s", bibliographic_changes.counts)

    with database_connection(settings) as connection:
        edition_changes = CatalogRepository(connection).edition_changes()
    logger.info("edition changes: %s", edition_changes.counts)

    edition_ids = sorted(edition_changes.to_insert)
    edition_records = []
    for start in range(0, len(edition_ids), settings.vega_page_size):
        edition_records.extend(
            await vega_client.fetch_editions(
                edition_ids[start : start + settings.vega_page_size]
            )
        )
    with database_connection(settings, write=True) as connection:
        repository = CatalogRepository(connection)
        repository.apply_edition_changes(edition_records, edition_changes)
        record_count = repository.rebuild_records()

    with database_connection(settings) as connection:
        repository = CatalogRepository(connection)
        embedding_changes = repository.embedding_changes()
        inputs = repository.embedding_inputs(sorted(embedding_changes.to_insert))
    logger.info("embedding changes: %s", embedding_changes.counts)

    new_embeddings: list[tuple[str, str]] = []
    if inputs:
        owned_embedding_client = embedding_client is None
        client = embedding_client or AsyncOpenAI(
            api_key=settings.require_openai_api_key()
        )
        try:
            new_embeddings = await create_record_embeddings(client, inputs, settings)
        finally:
            if owned_embedding_client:
                await client.close()

    with database_connection(settings, write=True) as connection:
        repository = CatalogRepository(connection)
        repository.apply_embedding_changes(new_embeddings, embedding_changes)
        prepare_vector_index(connection, settings)

    return SyncSummary(
        bibliographic=bibliographic_changes,
        editions=edition_changes,
        embeddings=embedding_changes,
        record_count=record_count,
    )


async def synchronize(
    settings: Settings,
    *,
    vega_client: VegaClient | None = None,
    embedding_client: Any | None = None,
) -> SyncSummary:
    settings.validate(require_openai_api_key=embedding_client is None)
    if vega_client is not None:
        return await _synchronize_with_vega(
            settings,
            vega_client,
            embedding_client=embedding_client,
        )

    async with VegaClient(settings) as owned_vega_client:
        return await _synchronize_with_vega(
            settings,
            owned_vega_client,
            embedding_client=embedding_client,
        )


def main() -> int:
    settings = Settings.from_env(require_openai_api_key=True)
    configure_logging(settings)
    logger.info("starting synchronization")
    summary = asyncio.run(synchronize(settings))
    logger.info("synchronization complete: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
