import pytest

from doc_alttext.config import PLACEHOLDER_API_KEY, resolve
from doc_alttext.errors import ConfigError


def test_missing_base_url_and_model_names_both():
    with pytest.raises(ConfigError) as exc:
        resolve()
    message = str(exc.value)
    assert "--base-url" in message and "DOC_ALTTEXT_BASE_URL" in message
    assert "--model" in message and "DOC_ALTTEXT_MODEL" in message


def test_missing_model_only():
    with pytest.raises(ConfigError) as exc:
        resolve(base_url="http://x/v1")
    assert "model" in str(exc.value)
    assert "--base-url" not in str(exc.value)


def test_arguments_win_over_env(monkeypatch):
    monkeypatch.setenv("DOC_ALTTEXT_BASE_URL", "http://env/v1")
    monkeypatch.setenv("DOC_ALTTEXT_MODEL", "env-model")
    s = resolve(base_url="http://arg/v1")
    assert s.base_url == "http://arg/v1"
    assert s.model == "env-model"


def test_api_key_is_optional():
    s = resolve(base_url="http://x/v1", model="m")
    assert s.api_key == PLACEHOLDER_API_KEY


def test_api_key_from_openai_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    assert resolve(base_url="http://x/v1", model="m").api_key == "sk-openai"


def test_own_api_key_env_wins(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("DOC_ALTTEXT_API_KEY", "sk-own")
    assert resolve(base_url="http://x/v1", model="m").api_key == "sk-own"


def test_defaults():
    s = resolve(base_url="http://x/v1", model="m")
    assert s.lang is None
    assert s.max_chars == 150
    assert s.max_images == 300
    assert s.max_image_side == 1024
    assert s.concurrency == 4


def test_numbers_from_env(monkeypatch):
    monkeypatch.setenv("DOC_ALTTEXT_MAX_CHARS", "120")
    monkeypatch.setenv("DOC_ALTTEXT_TIMEOUT", "30.5")
    s = resolve(base_url="http://x/v1", model="m")
    assert s.max_chars == 120
    assert s.timeout == 30.5


def test_invalid_env_number(monkeypatch):
    monkeypatch.setenv("DOC_ALTTEXT_MAX_IMAGES", "many")
    with pytest.raises(ConfigError, match="DOC_ALTTEXT_MAX_IMAGES"):
        resolve(base_url="http://x/v1", model="m")


def test_lang_from_env(monkeypatch):
    monkeypatch.setenv("DOC_ALTTEXT_LANG", "German")
    assert resolve(base_url="http://x/v1", model="m").lang == "German"


@pytest.mark.parametrize("name", ["max_chars", "max_file_mb", "max_images", "max_image_side", "concurrency", "timeout"])
def test_values_must_be_positive(name):
    with pytest.raises(ConfigError, match=name):
        resolve(base_url="http://x/v1", model="m", **{name: 0})


def test_negative_retries():
    with pytest.raises(ConfigError, match="max_retries"):
        resolve(base_url="http://x/v1", model="m", max_retries=-1)
