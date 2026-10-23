from .core import AltTexter, Result, add_alt_text, apply_alt_texts, default_output
from .errors import AltTextError, ConfigError, LimitError, ModelError, UnsupportedFileError
from .report import ImageItem, write_report

__version__ = "0.1.0"

__all__ = [
    "add_alt_text",
    "apply_alt_texts",
    "AltTexter",
    "Result",
    "ImageItem",
    "default_output",
    "write_report",
    "AltTextError",
    "ConfigError",
    "LimitError",
    "ModelError",
    "UnsupportedFileError",
    "__version__",
]
