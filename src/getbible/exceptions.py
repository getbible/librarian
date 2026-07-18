"""Public exception hierarchy for the getBible Librarian package."""


class GetBibleError(Exception):
    """Base exception for Librarian-specific failures."""


class ReferenceValidationError(ValueError, GetBibleError):
    """Raised when a scripture reference is malformed or cannot be resolved."""


class RequestLimitError(ReferenceValidationError):
    """Raised when otherwise valid input exceeds a configured work budget."""


class TranslationNotFoundError(FileNotFoundError, GetBibleError):
    """Raised when a requested translation is not available."""


class RepositoryError(GetBibleError):
    """Raised when the configured scripture repository cannot be read."""


class RepositoryTimeoutError(RepositoryError):
    """Raised when a repository request exceeds its connect or read timeout."""


class RepositoryResourceNotFound(RepositoryError):
    """Raised when a repository resource does not exist."""


class RepositoryResponseError(RepositoryError):
    """Raised when a repository response is malformed or cannot be decoded."""


class RepositoryResponseTooLarge(RepositoryResponseError):
    """Raised before an oversized repository response can exhaust memory."""


class CacheIntegrityError(GetBibleError):
    """Raised when downloaded content does not match its published checksum."""


class SearchValidationError(ValueError, GetBibleError):
    """Raised when a search query or its criteria are invalid."""
