class AltTextError(Exception):
    """Base class of all errors in this package."""


class ConfigError(AltTextError):
    """A setting is missing or a value is invalid."""


class LimitError(AltTextError):
    """A limit was exceeded."""


class UnsupportedFileError(AltTextError):
    """The file type is not supported or the file cannot be read."""


class ModelError(AltTextError):
    """The model server did not answer, or the answer was unusable."""
