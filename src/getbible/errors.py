"""Typed exceptions exposed by the GetBible client."""


class GetBibleError(Exception):
    """Base class for errors raised by the GetBible package."""


class InvalidReferenceError(ValueError, GetBibleError):
    """A Scripture reference is malformed, unsupported, or over its safety budget."""


class TranslationNotFoundError(FileNotFoundError, GetBibleError):
    """The requested translation is not available."""


class ScriptureNotFoundError(ValueError, FileNotFoundError, GetBibleError):
    """The requested chapter or verse does not exist."""


class UpstreamUnavailableError(GetBibleError):
    """The remote Scripture repository could not be reached safely."""


class DataValidationError(GetBibleError):
    """The Scripture repository returned malformed or unexpected data."""
