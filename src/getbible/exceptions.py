"""Public exception hierarchy for the getBible Librarian package."""


class GetBibleError(Exception):
    """Base exception for Librarian-specific failures."""


class RepositoryError(GetBibleError):
    """Raised when the configured scripture repository cannot be read."""


class RepositoryResourceNotFound(RepositoryError):
    """Raised when a repository resource does not exist."""


class RepositoryResponseError(RepositoryError):
    """Raised when a repository response is malformed or cannot be decoded."""


class CacheIntegrityError(GetBibleError):
    """Raised when downloaded content does not match its published checksum."""


class SearchValidationError(ValueError, GetBibleError):
    """Raised when a search query or its criteria are invalid."""
