"""Validated semantic search over stored catalog embeddings."""

import json
from typing import Any

from openai import OpenAI

from library_search.config import Settings
from library_search.db import (
    RECORD_COLUMNS,
    database_connection,
    require_current_schema,
)
from library_search.embeddings import create_query_embedding
from library_search.errors import InputValidationError, SearchError


def validate_query(query: str | None, settings: Settings) -> str:
    if query is None:
        raise InputValidationError("The query parameter is required")
    if not isinstance(query, str):
        raise InputValidationError("The query parameter must be text")
    normalized = query.strip()
    if not normalized:
        raise InputValidationError("The query parameter must not be blank")
    if len(normalized) > settings.maximum_query_length:
        raise InputValidationError(
            f"The query parameter must not exceed {settings.maximum_query_length} characters"
        )
    return normalized


def prepare_vector_index(connection, settings: Settings) -> None:
    connection.execute(
        "SELECT vector_init(" 
        "'embeddings', 'embedding', ?) ",
        (f"type=FLOAT32,dimension={settings.embedding_dimension}",),
    )
    connection.execute("SELECT vector_quantize('embeddings', 'embedding')")


def _search_rows(connection, query_embedding: list[float], settings: Settings):
    prepare_vector_index(connection, settings)
    connection.execute("DROP TABLE IF EXISTS nearest_neighbors")
    connection.execute(
        "CREATE TEMP TABLE nearest_neighbors AS "
        "SELECT e.id, v.distance FROM embeddings AS e "
        "JOIN vector_quantize_scan(" 
        "'embeddings', 'embedding', vector_as_f32(?), ?) AS v "
        "ON e.rowid = v.rowid",
        (json.dumps(query_embedding), settings.search_result_count),
    )
    return connection.execute(
        "SELECT r.*, n.distance FROM records AS r "
        "INNER JOIN nearest_neighbors AS n ON r.id = n.id "
        "ORDER BY n.distance"
    ).fetchall()


def _rows_to_records(rows) -> list[dict[str, Any]]:
    column_count = len(RECORD_COLUMNS)
    return [dict(zip(RECORD_COLUMNS, row[:column_count], strict=True)) for row in rows]


def search_catalog(
    settings: Settings,
    query: str | None,
    *,
    openai_client: Any | None = None,
) -> list[dict[str, Any]]:
    settings.validate(require_openai_api_key=openai_client is None)
    normalized_query = validate_query(query, settings)
    owned_client = openai_client is None
    client = openai_client or OpenAI(api_key=settings.require_openai_api_key())
    try:
        query_embedding = create_query_embedding(client, normalized_query, settings)
        with database_connection(settings, write=True) as connection:
            require_current_schema(connection)
            rows = _search_rows(connection, query_embedding, settings)
        return _rows_to_records(rows)
    except (InputValidationError, SearchError):
        raise
    except Exception as error:
        raise SearchError("Semantic search failed") from error
    finally:
        if owned_client:
            client.close()
