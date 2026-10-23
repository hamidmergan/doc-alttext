"""Calls to an OpenAI-compatible chat endpoint."""

import base64
import json
import re
from dataclasses import dataclass
from typing import Optional

from .config import Settings
from .errors import ModelError

LANGUAGE_PROMPT = (
    "Name the main language of the text below. "
    "Answer with the English name of the language only, for example: German"
)

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass(frozen=True)
class Answer:
    decorative: bool
    alt: str


def make_client(settings: Settings):
    from openai import OpenAI

    return OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=settings.timeout,
        max_retries=settings.max_retries,
    )


def _chat(client, settings: Settings, messages: list) -> str:
    import openai

    try:
        response = client.chat.completions.create(model=settings.model, temperature=0, messages=messages)
    except openai.APITimeoutError:
        raise ModelError(
            f"Request to {settings.base_url} timed out after {settings.timeout:g} seconds. "
            "Increase --timeout or DOC_ALTTEXT_TIMEOUT, or use a faster model."
        )
    except Exception as exc:
        raise ModelError(f"Request to {settings.base_url} failed: {exc}")
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        raise ModelError("The server response has an unexpected format.")
    return _THINK.sub("", content or "").strip()


def system_prompt(settings: Settings, language: str) -> str:
    return settings.prompt.replace("{language}", language).replace("{max_chars}", str(settings.max_chars))


def describe_image(client, settings: Settings, png: bytes, context: str, language: str) -> Answer:
    """Ask the model for alt text, or whether the image is decorative."""
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    messages = [
        {"role": "system", "content": system_prompt(settings, language)},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Context from the document:\n" + (context or "(none)")},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    return parse_answer(_chat(client, settings, messages))


def parse_answer(text: str) -> Answer:
    """Read the model answer. Plain text without JSON counts as the alt text itself."""
    data = _json_object(text)
    if data is None:
        plain = _clean(_FENCE.sub("", text))
        if not plain or plain.startswith("{"):
            raise ModelError(f"The model answer is not usable: {text[:200]!r}")
        return Answer(decorative=False, alt=plain)
    decorative = data.get("decorative", False)
    if isinstance(decorative, str):
        decorative = decorative.strip().lower() in ("true", "yes", "1")
    alt = data.get("alt")
    alt = _clean(alt) if isinstance(alt, str) else ""
    if decorative:
        return Answer(decorative=True, alt="")
    if not alt:
        raise ModelError("The model returned no alt text and did not mark the image as decorative.")
    return Answer(decorative=False, alt=alt)


def detect_language(client, settings: Settings, sample: str) -> Optional[str]:
    """English name of the main language of the sample, or None if the answer is unusable."""
    messages = [
        {"role": "system", "content": LANGUAGE_PROMPT},
        {"role": "user", "content": sample},
    ]
    answer = _chat(client, settings, messages)
    first = answer.splitlines()[0] if answer else ""
    name = first.strip().strip(".\"'*` ")
    if not name or len(name) > 40:
        return None
    return name


def _clean(text: str) -> str:
    text = " ".join(text.split())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def _json_object(text: str) -> Optional[dict]:
    """The first top-level JSON object in the text, skipping chatter around it."""
    decoder = json.JSONDecoder(strict=False)  # models sometimes put raw newlines in strings
    for match in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None
