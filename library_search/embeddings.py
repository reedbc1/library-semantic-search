"""Embedding creation and response validation."""

import asyncio
import math
from collections.abc import Sequence
from typing import Any

from library_search.config import Settings
from library_search.errors import EmbeddingError
from library_search.models import EmbeddingInput


def validate_embedding(value: Any, settings: Settings) -> list[float]:
    if not isinstance(value, (list, tuple)):
        raise EmbeddingError("Embedding must be a list of numbers")
    if len(value) != settings.embedding_dimension:
        raise EmbeddingError(
            f"Embedding dimension must be {settings.embedding_dimension}, "
            f"received {len(value)}"
        )

    embedding: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise EmbeddingError("Embedding contains a non-numeric component")
        number = float(component)
        if not math.isfinite(number):
            raise EmbeddingError("Embedding contains a non-finite component")
        embedding.append(number)
    return embedding


async def create_record_embedding(
    client: Any,
    record: EmbeddingInput,
    settings: Settings,
) -> tuple[str, str]:
    try:
        response = await client.embeddings.create(
            input=record.text,
            model=settings.embedding_model,
        )
        embedding = validate_embedding(response.data[0].embedding, settings)
        return record.id, str(embedding)
    except EmbeddingError:
        raise
    except Exception as error:
        raise EmbeddingError(f"Could not embed catalog record {record.id}") from error


async def create_record_embeddings(
    client: Any,
    records: Sequence[EmbeddingInput],
    settings: Settings,
) -> list[tuple[str, str]]:
    embeddings: list[tuple[str, str]] = []
    for start in range(0, len(records), settings.embedding_batch_size):
        batch = records[start : start + settings.embedding_batch_size]
        embeddings.extend(
            await asyncio.gather(
                *(create_record_embedding(client, record, settings) for record in batch)
            )
        )
    return embeddings


def create_query_embedding(client: Any, query: str, settings: Settings) -> list[float]:
    try:
        response = client.embeddings.create(
            input=query,
            model=settings.embedding_model,
        )
        return validate_embedding(response.data[0].embedding, settings)
    except EmbeddingError:
        raise
    except Exception as error:
        raise EmbeddingError("Could not embed the search query") from error
