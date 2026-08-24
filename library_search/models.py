"""Typed records passed between integration, sync, and persistence layers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BibliographicRecord:
    id: str
    title: str
    publication_date: str
    cover_url: str | None
    edition_id: str

    def as_database_tuple(self) -> tuple[str, str, str, str | None, str]:
        return (
            self.id,
            self.title,
            self.publication_date,
            self.cover_url,
            self.edition_id,
        )


@dataclass(frozen=True)
class EditionRecord:
    id: str
    author: str
    item_language: str
    subjects: str
    summary: str

    def as_database_tuple(self) -> tuple[str, str, str, str, str]:
        return (
            self.id,
            self.author,
            self.item_language,
            self.subjects,
            self.summary,
        )


@dataclass(frozen=True)
class EmbeddingInput:
    id: str
    text: str


@dataclass(frozen=True)
class ChangeSet:
    to_insert: frozenset[str]
    to_delete: frozenset[str]
    unchanged: frozenset[str]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "insert": len(self.to_insert),
            "delete": len(self.to_delete),
            "unchanged": len(self.unchanged),
        }
