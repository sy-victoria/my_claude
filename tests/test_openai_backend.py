"""本地模拟 OpenAI Chat Completions，验证另一后端的完整工具循环。"""

from __future__ import annotations

import json
import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from minicode.agent import Agent
from minicode.openai_backend import OpenAIChatAdapter


def test_ollama_compatible_tool_roundtrip_without_api_key():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            assert self.headers.get("Authorization") is None
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            if len(requests) == 1:
                message = {"content": None, "tool_calls": [{"id": "tool-1", "type": "function",
                           "function": {"name": "unknown", "arguments": "{}"}}]}
                reason = "tool_calls"
            else:
                message = {"content": "已处理", "tool_calls": None}
                reason = "stop"
            body = json.dumps({"choices": [{"message": message, "finish_reason": reason}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 3}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        agent = Agent(provider="ollama", model="local-test",
                      base_url=f"http://127.0.0.1:{server.server_port}/v1")
        assert agent.run_turn("试用工具") == "已处理"
        assert agent.last_stop_reason == "end_turn"
        assert agent.context.cumulative_tokens == 26
        assert requests[0]["tools"][0]["type"] == "function"
        assert requests[1]["messages"][-2]["tool_calls"][0]["id"] == "tool-1"
        assert requests[1]["messages"][-1]["role"] == "tool"
        assert requests[1]["messages"][-1]["tool_call_id"] == "tool-1"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_remote_openai_backend_requires_https_for_api_key():
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAIChatAdapter("http://127.0.0.1:1234/v1", "secret")


def test_openai_backend_requires_explicit_model():
    with pytest.raises(ValueError, match="指定 model"):
        Agent(provider="ollama")


def test_openai_endpoint_sends_bearer_to_configured_https_host(monkeypatch):
    seen = {}
    class Opener:
        def open(self, request, timeout):
            seen["url"] = request.full_url
            seen["authorization"] = request.get_header("Authorization")
            seen["payload"] = json.loads(request.data)
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"},
                                                     "finish_reason": "stop"}]}).encode())

    monkeypatch.setattr("minicode.openai_backend.urllib.request.build_opener", lambda *_args: Opener())
    response = OpenAIChatAdapter("https://api.example.com/v1", "secret").create(
        model="test-model", max_tokens=100, system="hello", messages=[{"role": "user", "content": "hi"}])
    assert response.content[0].text == "ok"
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["authorization"] == "Bearer secret"
    assert seen["payload"]["messages"][0] == {"role": "system", "content": "hello"}
