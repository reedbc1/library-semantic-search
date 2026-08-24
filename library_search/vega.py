"""Validated asynchronous client for the III Vega catalog API."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import httpx

from library_search.config import Settings
from library_search.errors import InputValidationError, VegaError
from library_search.models import BibliographicRecord, EditionRecord


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(f"Vega field {field} must be an object")
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise InputValidationError(f"Vega field {field} must be a list")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(f"Vega field {field} must be non-empty text")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputValidationError(f"Vega field {field} must be text or null")
    return value


def _joined_text(value: Any, field: str) -> str:
    if isinstance(value, str):
        return value
    values = _sequence(value if value is not None else [], field)
    if not all(isinstance(item, str) for item in values):
        raise InputValidationError(f"Vega field {field} must contain only text")
    return ", ".join(values)


class VegaClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: Any | None = None,
    ):
        self.settings = settings
        self._client = http_client
        self._owns_client = http_client is None
        self._semaphore = asyncio.Semaphore(settings.request_concurrency)

    async def __aenter__(self) -> "VegaClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds
            )
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        domain = self.settings.vega_customer_domain
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "api-version": "2",
            "content-type": "application/json",
            "iii-customer-domain": domain,
            "iii-host-domain": domain,
            "Referer": f"https://{domain}/",
        }

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("VegaClient must be used as an async context manager")
        return self._client

    async def _request_json(
        self, method: str, url: str, **kwargs: Any
    ) -> Mapping[str, Any]:
        client = self._require_client()
        try:
            async with self._semaphore:
                if method == "GET":
                    response = await client.get(url, **kwargs)
                else:
                    response = await client.post(url, **kwargs)
            response.raise_for_status()
            return _mapping(response.json(), "response")
        except (httpx.HTTPError, InputValidationError, ValueError) as error:
            raise VegaError(f"Vega {method} request failed for {url}") from error

    async def total_bibliographic_pages(
        self, date_from: int, date_to: int
    ) -> int:
        response = await self._bibliographic_response(
            date_from=date_from,
            date_to=date_to,
            page_number=0,
        )
        total_pages = response.get("totalPages")
        if not isinstance(total_pages, int) or total_pages < 0:
            raise VegaError("Vega totalPages must be a non-negative integer")
        return total_pages

    async def _bibliographic_response(
        self,
        *,
        date_from: int,
        date_to: int,
        page_number: int,
    ) -> Mapping[str, Any]:
        if date_from < 1 or date_to < date_from or page_number < 0:
            raise InputValidationError("Invalid Vega date or page range")
        url = f"{self.settings.vega_base_url.rstrip('/')}/search-result/search/format-groups"
        payload = {
            "searchText": self.settings.vega_search_text,
            "sorting": "title",
            "sortOrder": "asc",
            "searchType": "everything",
            "universalLimiterIds": [self.settings.vega_limiter_id],
            "materialTypeIds": [self.settings.vega_material_type_id],
            "locationIds": [self.settings.vega_location_id],
            "pageNum": page_number,
            "pageSize": self.settings.vega_page_size,
            "resourceType": "FormatGroup",
            "dateFrom": date_from,
            "dateTo": date_to,
        }
        return await self._request_json(
            "POST", url, headers=self._headers, json=payload
        )

    async def fetch_bibliographic_page(
        self,
        *,
        date_from: int,
        date_to: int,
        page_number: int,
    ) -> list[BibliographicRecord]:
        response = await self._bibliographic_response(
            date_from=date_from,
            date_to=date_to,
            page_number=page_number,
        )
        data = _sequence(response.get("data"), "data")
        records: list[BibliographicRecord] = []
        try:
            for index, raw_record in enumerate(data):
                record = _mapping(raw_record, f"data[{index}]")
                cover = _mapping(record.get("coverUrl", {}), "coverUrl")
                material_tabs = _sequence(
                    record.get("materialTabs"), "materialTabs"
                )
                if not material_tabs:
                    raise VegaError("Vega bibliographic record has no material tab")
                first_tab = _mapping(material_tabs[0], "materialTabs[0]")
                editions = _sequence(first_tab.get("editions"), "editions")
                if not editions:
                    raise VegaError("Vega bibliographic record has no edition")
                first_edition = _mapping(editions[0], "editions[0]")
                records.append(
                    BibliographicRecord(
                        id=_required_text(record.get("id"), "id"),
                        title=_required_text(record.get("title"), "title"),
                        publication_date=_required_text(
                            record.get("publicationDate"), "publicationDate"
                        ),
                        cover_url=_optional_text(
                            cover.get("medium"), "coverUrl.medium"
                        ),
                        edition_id=_required_text(
                            first_edition.get("id"), "edition.id"
                        ),
                    )
                )
        except InputValidationError as error:
            raise VegaError("Vega bibliographic response is invalid") from error
        return records

    async def _fetch_bibliographic_range(
        self, date_from: int, date_to: int
    ) -> list[BibliographicRecord]:
        total_pages = await self.total_bibliographic_pages(date_from, date_to)
        pages = await asyncio.gather(
            *(
                self.fetch_bibliographic_page(
                    date_from=date_from,
                    date_to=date_to,
                    page_number=page_number,
                )
                for page_number in range(total_pages + 1)
            )
        )
        return [record for page in pages for record in page]

    async def fetch_all_bibliographic_records(
        self,
    ) -> list[BibliographicRecord]:
        records = await self._fetch_bibliographic_range(1, 1999)
        for year in range(2000, date.today().year + 1):
            records.extend(await self._fetch_bibliographic_range(year, year))
        unique_records = {record.id: record for record in records}
        if len(unique_records) != len(records):
            raise VegaError("Vega returned duplicate bibliographic IDs")
        return list(unique_records.values())

    async def fetch_edition(self, edition_id: str) -> EditionRecord:
        identifier = _required_text(edition_id, "edition_id")
        url = (
            f"{self.settings.vega_base_url.rstrip('/')}/search-result/editions/"
            f"{identifier}"
        )
        headers = {**self._headers, "api-version": "1"}
        response = await self._request_json("GET", url, headers=headers)
        try:
            edition = _mapping(response.get("edition"), "edition")

            subjects: list[str] = []
            for key, value in edition.items():
                if key.startswith("subj"):
                    subject_values = _sequence(value, key)
                    if not all(
                        isinstance(subject, str) for subject in subject_values
                    ):
                        raise VegaError(f"Vega field {key} must contain only text")
                    subjects.extend(subject_values)

            return EditionRecord(
                id=identifier,
                author=_joined_text(edition.get("author", []), "author"),
                item_language=_joined_text(
                    edition.get("itemLanguage", []), "itemLanguage"
                ),
                subjects=", ".join(subjects),
                summary=_joined_text(
                    edition.get("noteSummary", []), "noteSummary"
                ),
            )
        except InputValidationError as error:
            raise VegaError(f"Vega edition {identifier} is invalid") from error

    async def fetch_editions(
        self, edition_ids: Sequence[str]
    ) -> list[EditionRecord]:
        return list(
            await asyncio.gather(
                *(self.fetch_edition(edition_id) for edition_id in edition_ids)
            )
        )
