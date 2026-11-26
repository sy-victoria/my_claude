"""MCP 客户端测试：真实拉起迷你 server 子进程做集成测试（不调 LLM API）。"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from minicode.mcp_client import HttpMcpServer, McpServer, load_mcp_tools, wrap_as_tools


@pytest.fixture(autouse=True)
def transport_without_sandbox_on_windows(monkeypatch):
    """协议测试单独验证传输；Windows 沙箱暂未实现。"""
    if os.name != "posix":
        monkeypatch.setattr("minicode.mcp_client.sandbox_argv", lambda argv, **_kwargs: (argv, os.environ.copy()))

SERVER_PATH = str(Path(__file__).parent / "mini_mcp_server.py")


def test_http_mcp_json_transport():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(payload["method"])
            if "id" not in payload:
                self.send_response(202)
                self.end_headers()
                return
            result = {"tools": [{"name": "ping", "inputSchema": {"type": "object"}}]} if payload["method"] == "tools/list" else {}
            if payload["method"] == "tools/call":
                result = {"content": [{"type": "text", "text": "pong"}]}
            body = json.dumps({"jsonrpc": "2.0", "id": payload["id"], "result": result}).encode()
            is_sse = payload["method"] == "tools/list"
            if is_sse:
                body = b"data: " + body + b"\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if is_sse else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HttpMcpServer("local", f"http://127.0.0.1:{server.server_port}")
        client.initialize()
        assert client.list_tools()[0]["name"] == "ping"
        assert client.call_tool("ping", {}) == "pong"
        assert calls == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def server():
    s = McpServer("calc", [sys.executable, SERVER_PATH])
    s.initialize()
    yield s
    s.close()


def test_handshake_and_list_tools(server):
    tools = server.list_tools()

    assert tools[0]["name"] == "add"
    assert "inputSchema" in tools[0]


def test_call_tool_returns_text(server):
    result = server.call_tool("add", {"a": 2, "b": 3})

    assert result == "5"


def test_call_unknown_tool_reports_error(server):
    result = server.call_tool("nope", {})

    assert "出错" in result


def test_wrap_as_tools_prefixes_name_and_execute_level(server):
    tools = wrap_as_tools(server)

    assert tools[0].name == "mcp__calc__add"
    assert tools[0].permission_level == "execute"
    assert tools[0].run({"a": 40, "b": 2}) == "42"


def test_load_mcp_tools_from_config(tmp_path):
    (tmp_path / ".minicode").mkdir()
    (tmp_path / ".minicode" / "mcp.json").write_text(
        json.dumps({"servers": {"calc": {"command": [sys.executable, SERVER_PATH]}}})
    )

    tools = load_mcp_tools(tmp_path)

    assert [t.name for t in tools] == ["mcp__calc__add"]


def test_load_mcp_tools_without_config_is_empty(tmp_path):
    assert load_mcp_tools(tmp_path) == []


def test_project_cannot_auto_connect_remote_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr("minicode.mcp_client.Path.home", lambda: tmp_path / "home")
    (tmp_path / ".minicode").mkdir()
    (tmp_path / ".minicode" / "mcp.json").write_text(
        json.dumps({"servers": {"outside": {"url": "https://example.com/mcp",
                                               "token_env": "ANTHROPIC_API_KEY"}}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="用户级"):
        load_mcp_tools(tmp_path)
