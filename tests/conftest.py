import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def default_reply(body: dict) -> str:
    """Language request: a language name. Image request: alt text that names the request number."""
    user = body["messages"][-1]["content"]
    if isinstance(user, str):
        return "German"
    return json.dumps({"decorative": False, "alt": "A test image"})


class FakeServer:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.delay = 0
        self.reply = default_reply
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                outer.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if outer.delay:
                    time.sleep(outer.delay)
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                payload = {
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": outer.reply(body)},
                        }
                    ],
                }
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    @property
    def image_requests(self):
        return [r for r in self.requests if not isinstance(r["body"]["messages"][-1]["content"], str)]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.stop()


@pytest.fixture
def settings(server):
    from doc_alttext.config import resolve

    return resolve(base_url=server.base_url, model="vision", max_retries=0)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith("DOC_ALTTEXT_") or name == "OPENAI_API_KEY":
            monkeypatch.delenv(name)
