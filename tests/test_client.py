import json

import pytest

from doc_alttext.client import Answer, describe_image, detect_language, make_client, parse_answer
from doc_alttext.config import resolve
from doc_alttext.errors import ModelError

PNG = b"\x89PNG fake"


def test_describe_sends_prompt_context_and_image(server, settings):
    answer = describe_image(make_client(settings), settings, PNG, "Slide 2. Title: Results", "German")
    assert answer == Answer(decorative=False, alt="A test image")
    body = server.requests[0]["body"]
    assert body["model"] == "vision"
    system = body["messages"][0]["content"]
    assert "Write it in German." in system
    assert "at most 150 characters" in system
    text, image = body["messages"][1]["content"]
    assert "Title: Results" in text["text"]
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_placeholder_key_is_sent_without_api_key(server, settings):
    describe_image(make_client(settings), settings, PNG, "", "English")
    assert server.requests[0]["headers"]["authorization"] == "Bearer not-needed"


def test_api_key_is_sent(server):
    s = resolve(base_url=server.base_url, model="vision", api_key="sk-test", max_retries=0)
    describe_image(make_client(s), s, PNG, "", "English")
    assert server.requests[0]["headers"]["authorization"] == "Bearer sk-test"


def test_custom_max_chars_in_prompt(server):
    s = resolve(base_url=server.base_url, model="vision", max_chars=90, max_retries=0)
    describe_image(make_client(s), s, PNG, "", "English")
    assert "at most 90 characters" in server.requests[0]["body"]["messages"][0]["content"]


def test_server_error_is_model_error(server, settings):
    server.status = 500
    with pytest.raises(ModelError, match="failed"):
        describe_image(make_client(settings), settings, PNG, "", "English")


def test_detect_language(server, settings):
    assert detect_language(make_client(settings), settings, "Hallo Welt") == "German"
    assert server.requests[0]["body"]["messages"][1]["content"] == "Hallo Welt"


def test_detect_language_unusable_answer(server, settings):
    server.reply = lambda body: "x" * 100
    assert detect_language(make_client(settings), settings, "text") is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"decorative": false, "alt": "Bar chart: sales doubled"}', Answer(False, "Bar chart: sales doubled")),
        ('```json\n{"decorative": true, "alt": ""}\n```', Answer(True, "")),
        ('<think>hmm {"a": 1}</think>{"decorative": false, "alt": "Logo"}', Answer(False, "Logo")),
        ('Sure! {"decorative": "true"}', Answer(True, "")),
        ('{"decorative": false, "alt": "  two   spaces\n"}', Answer(False, "two spaces")),
        ('"A red apple on a table"', Answer(False, "A red apple on a table")),
    ],
)
def test_parse_answer(text, expected):
    from doc_alttext.client import _THINK

    assert parse_answer(_THINK.sub("", text)) == expected


@pytest.mark.parametrize("text", ["", '{"decorative": false, "alt": ""}', '{"broken": '])
def test_parse_answer_unusable(text):
    with pytest.raises(ModelError):
        parse_answer(text)


def test_think_block_removed_from_server_answer(server, settings):
    server.reply = lambda body: "<think>" + json.dumps({"alt": "no"}) + "</think>" + json.dumps({"alt": "Yes"})
    assert describe_image(make_client(settings), settings, PNG, "", "English").alt == "Yes"


def test_timeout_suggests_setting(server):
    server.delay = 0.5
    s = resolve(base_url=server.base_url, model="vision", timeout=0.1, max_retries=0)
    with pytest.raises(ModelError, match="timed out after 0.1 seconds. Increase --timeout"):
        describe_image(make_client(s), s, PNG, "", "English")
