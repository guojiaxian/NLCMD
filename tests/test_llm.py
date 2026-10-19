import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nlcmd.llm import LLMClient, LLMError


class Handler(BaseHTTPRequestHandler):
    last_bodies = []  # 记录收到的请求体，供断言 payload 内容

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        Handler.last_bodies.append(body)
        if body.get("model") == "bad-key":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "invalid key"}')
            return
        if body.get("model") == "boom":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"server error")
            return
        resp = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "commands": [
                                    {"command": "echo hi", "description": "问好", "risk": "safe"}
                                ]
                            }
                        ),
                    }
                }
            ]
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:{}".format(httpd.server_port)
    httpd.shutdown()


def test_chat_ok(server):
    client = LLMClient(api_base=server, api_key="k", model="m", timeout=5)
    out = client.chat([{"role": "user", "content": "hi"}])
    assert "echo hi" in out


def test_chat_401(server):
    client = LLMClient(api_base=server, api_key="k", model="bad-key", timeout=5)
    with pytest.raises(LLMError) as e:
        client.chat([{"role": "user", "content": "hi"}])
    assert "Key" in e.value.message


def test_chat_500(server):
    client = LLMClient(api_base=server, api_key="k", model="boom", timeout=5)
    with pytest.raises(LLMError) as e:
        client.chat([{"role": "user", "content": "hi"}])
    assert "服务端错误" in e.value.message


def test_chat_connect_error():
    client = LLMClient(api_base="http://127.0.0.1:1", api_key="k", model="m", timeout=2)
    with pytest.raises(LLMError) as e:
        client.chat([{"role": "user", "content": "hi"}])
    assert "无法连接" in e.value.message


def test_missing_api_base():
    client = LLMClient(api_base="", api_key="k", model="m")
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "hi"}])


def test_test_connection_ok(server):
    client = LLMClient(api_base=server, api_key="k", model="m", timeout=5)
    ok, msg = client.test_connection()
    assert ok
    assert "成功" in msg


def test_disable_thinking_payload(server):
    # 开启 disable_thinking 时，payload 必须带 thinking={"type":"disabled"}（官方文档格式）
    Handler.last_bodies.clear()
    client = LLMClient(api_base=server, api_key="k", model="m", timeout=5,
                       disable_thinking=True)
    client.chat([{"role": "user", "content": "hi"}])
    assert Handler.last_bodies[-1]["thinking"] == {"type": "disabled"}


def test_thinking_not_sent_by_default(server):
    Handler.last_bodies.clear()
    client = LLMClient(api_base=server, api_key="k", model="m", timeout=5)
    client.chat([{"role": "user", "content": "hi"}])
    assert "thinking" not in Handler.last_bodies[-1]
