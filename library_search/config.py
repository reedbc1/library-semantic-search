"""Typed application configuration loaded at executable boundaries."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

from library_search.errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolved_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _integer(source: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(source.get(name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error


def _number(source: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(source.get(name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error


@dataclass(frozen=True)
class Settings:
    project_root: Path
    database_path: Path
    log_path: Path
    openai_api_key: str | None
    vega_base_url: str = "https://na2.iiivega.com/api"
    vega_customer_domain: str = "slouc.na2.iiivega.com"
    vega_search_text: str = "*"
    vega_material_type_id: str = "1"
    vega_location_id: str = "59"
    vega_limiter_id: str = "at_library"
    vega_page_size: int = 100
    request_concurrency: int = 5
    request_timeout_seconds: float = 60.0
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    embedding_batch_size: int = 100
    search_result_count: int = 100
    maximum_query_length: int = 1000
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        project_root: Path | None = None,
        require_openai_api_key: bool = False,
    ) -> "Settings":
        root = (project_root or PROJECT_ROOT).expanduser().resolve()
        if environ is None:
            load_dotenv(root / ".env")
            source: Mapping[str, str] = os.environ
        else:
            source = environ

        settings = cls(
            project_root=root,
            database_path=_resolved_path(
                root, source.get("DATABASE_PATH", "items.db")
            ),
            log_path=_resolved_path(root, source.get("LOG_PATH", "history.log")),
            openai_api_key=source.get("OPENAI_API_KEY"),
            vega_base_url=source.get(
                "VEGA_BASE_URL", "https://na2.iiivega.com/api"
            ),
            vega_customer_domain=source.get(
                "VEGA_CUSTOMER_DOMAIN", "slouc.na2.iiivega.com"
            ),
            vega_search_text=source.get("VEGA_SEARCH_TEXT", "*"),
            vega_material_type_id=source.get("VEGA_MATERIAL_TYPE_ID", "1"),
            vega_location_id=source.get("VEGA_LOCATION_ID", "59"),
            vega_limiter_id=source.get("VEGA_LIMITER_ID", "at_library"),
            vega_page_size=_integer(source, "VEGA_PAGE_SIZE", 100),
            request_concurrency=_integer(source, "REQUEST_CONCURRENCY", 5),
            request_timeout_seconds=_number(
                source, "REQUEST_TIMEOUT_SECONDS", 60.0
            ),
            embedding_model=source.get(
                "EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            embedding_dimension=_integer(source, "EMBEDDING_DIMENSION", 1536),
            embedding_batch_size=_integer(source, "EMBEDDING_BATCH_SIZE", 100),
            search_result_count=_integer(source, "SEARCH_RESULT_COUNT", 100),
            maximum_query_length=_integer(source, "MAXIMUM_QUERY_LENGTH", 1000),
            log_level=source.get("LOG_LEVEL", "INFO").upper(),
        )
        settings.validate(require_openai_api_key=require_openai_api_key)
        return settings

    def validate(self, *, require_openai_api_key: bool = False) -> None:
        positive_integers = {
            "vega_page_size": self.vega_page_size,
            "request_concurrency": self.request_concurrency,
            "embedding_dimension": self.embedding_dimension,
            "embedding_batch_size": self.embedding_batch_size,
            "search_result_count": self.search_result_count,
            "maximum_query_length": self.maximum_query_length,
        }
        for name, value in positive_integers.items():
            if value <= 0:
                raise ConfigurationError(f"{name} must be greater than zero")

        if self.request_timeout_seconds <= 0:
            raise ConfigurationError(
                "request_timeout_seconds must be greater than zero"
            )
        if not self.vega_base_url.startswith(("http://", "https://")):
            raise ConfigurationError("vega_base_url must be an HTTP(S) URL")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(f"Unsupported log_level: {self.log_level}")

        required_text = {
            "vega_customer_domain": self.vega_customer_domain,
            "vega_search_text": self.vega_search_text,
            "vega_material_type_id": self.vega_material_type_id,
            "vega_location_id": self.vega_location_id,
            "vega_limiter_id": self.vega_limiter_id,
            "embedding_model": self.embedding_model,
        }
        for name, value in required_text.items():
            if not value.strip():
                raise ConfigurationError(f"{name} must not be blank")

        if require_openai_api_key and not (self.openai_api_key or "").strip():
            raise ConfigurationError("OPENAI_API_KEY is required")

    def require_openai_api_key(self) -> str:
        self.validate(require_openai_api_key=True)
        return self.openai_api_key or ""
