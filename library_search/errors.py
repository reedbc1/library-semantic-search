"""Application-specific exception types."""


class ApplicationError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(ApplicationError):
    """Raised when application settings are invalid or incomplete."""


class InputValidationError(ApplicationError):
    """Raised when input at an application boundary is invalid."""


class VegaError(ApplicationError):
    """Raised when Vega cannot be reached or returns an invalid response."""


class EmbeddingError(ApplicationError):
    """Raised when an embedding request or response is invalid."""


class DatabaseError(ApplicationError):
    """Raised for application-level database failures."""


class MigrationError(DatabaseError):
    """Raised when a schema migration cannot be applied safely."""


class SearchError(ApplicationError):
    """Raised when semantic search cannot be completed."""
