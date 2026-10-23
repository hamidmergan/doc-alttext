"""Default values and resolution of settings.

Order: argument, then environment variable, then default.
"""

import os
from dataclasses import dataclass
from typing import Optional

from .errors import ConfigError

# Limits
MAX_FILE_MB = 100
MAX_IMAGES = 300
MAX_IMAGE_SIDE = 1024

# Alt text
MAX_CHARS = 150

# Processing
CONCURRENCY = 4
TIMEOUT_SECONDS = 120
MAX_RETRIES = 2

# Placeholder, because the OpenAI library requires a value. Local servers ignore it.
PLACEHOLDER_API_KEY = "not-needed"

ENV_PREFIX = "DOC_ALTTEXT_"

DEFAULT_PROMPT = """You write alt text for images in a document, for people who use a screen reader.
You get the image and context from the document around it.

Answer with one JSON object and nothing else:
{"decorative": false, "alt": "..."} for an image that carries information, or
{"decorative": true, "alt": ""} for a purely decorative image.

Rules for the alt text:
- Write it in {language}.
- Keep it short, at most {max_chars} characters. One sentence or a short phrase.
- Describe what the image shows and why it matters in this document. Use the context.
- Do not start with "Image of", "Picture of", "Photo of" or the same words in another language.
- For a chart or diagram, state the key message (trend, comparison, result), not every value.
- If the image contains important text, include that text.
- Do not repeat the caption word for word. Add what the caption does not say.
- Do not guess names of people, places or brands that neither the image nor the context gives.

An image is decorative if it adds no information: lines, borders, backgrounds, ornaments,
spacers, or a logo repeated as branding on many pages or slides.
If you are not sure, write alt text. Do not mark photos, illustrations, charts or diagrams as decorative."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_key: str
    lang: Optional[str]
    max_chars: int
    max_file_mb: float
    max_images: int
    max_image_side: int
    concurrency: int
    timeout: float
    max_retries: int
    prompt: str


def _env(name: str) -> Optional[str]:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _pick(arg, env_name: str, default, cast):
    if arg is not None:
        return arg
    raw = _env(env_name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ConfigError(f"Environment variable {ENV_PREFIX}{env_name} has an invalid value: {raw!r}")


def resolve(
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    lang: Optional[str] = None,
    max_chars: Optional[int] = None,
    max_file_mb: Optional[float] = None,
    max_images: Optional[int] = None,
    max_image_side: Optional[int] = None,
    concurrency: Optional[int] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    prompt: Optional[str] = None,
) -> Settings:
    base_url = _pick(base_url, "BASE_URL", None, str)
    model = _pick(model, "MODEL", None, str)
    missing = []
    if not base_url:
        missing.append(f"base_url (--base-url or {ENV_PREFIX}BASE_URL)")
    if not model:
        missing.append(f"model (--model or {ENV_PREFIX}MODEL)")
    if missing:
        raise ConfigError(
            "Missing: " + " and ".join(missing) + ". "
            "Example for Ollama: base_url http://localhost:11434/v1 and a vision model."
        )

    key = _pick(api_key, "API_KEY", None, str)
    if not key:
        key = os.environ.get("OPENAI_API_KEY") or PLACEHOLDER_API_KEY

    settings = Settings(
        base_url=base_url,
        model=model,
        api_key=key,
        lang=_pick(lang, "LANG", None, str) or None,
        max_chars=_pick(max_chars, "MAX_CHARS", MAX_CHARS, int),
        max_file_mb=_pick(max_file_mb, "MAX_FILE_MB", MAX_FILE_MB, float),
        max_images=_pick(max_images, "MAX_IMAGES", MAX_IMAGES, int),
        max_image_side=_pick(max_image_side, "MAX_IMAGE_SIDE", MAX_IMAGE_SIDE, int),
        concurrency=_pick(concurrency, "CONCURRENCY", CONCURRENCY, int),
        timeout=_pick(timeout, "TIMEOUT", TIMEOUT_SECONDS, float),
        max_retries=_pick(max_retries, "MAX_RETRIES", MAX_RETRIES, int),
        prompt=_pick(prompt, "PROMPT", DEFAULT_PROMPT, str),
    )
    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    positive = {
        "max_chars": s.max_chars,
        "max_file_mb": s.max_file_mb,
        "max_images": s.max_images,
        "max_image_side": s.max_image_side,
        "concurrency": s.concurrency,
        "timeout": s.timeout,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ConfigError(f"{name} must be greater than 0, but is {value}.")
    if s.max_retries < 0:
        raise ConfigError("max_retries must not be negative.")
