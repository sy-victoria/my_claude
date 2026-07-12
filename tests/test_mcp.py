"""MCP 客户端测试：真实拉起迷你 server 子进程做集成测试（不调 LLM API）。"""

import json
from pathlib import Path

import pytest

from minicode.mcp_client import McpServer, load_mcp_tools, wrap_as_tools

SERVER_PATH = str(Path(__file__).parent / "mini_mcp_server.py")


@pytest.fixture
def server():
    s = McpServer("calc", ["python3", SERVER_PATH])
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
        json.dumps({"servers": {"calc": {"command": ["python3", SERVER_PATH]}}})
    )

    tools = load_mcp_tools(tmp_path)

    assert [t.name for t in tools] == ["mcp__calc__add"]


def test_load_mcp_tools_without_config_is_empty(tmp_path):
    assert load_mcp_tools(tmp_path) == []
