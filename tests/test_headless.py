"""非交互输出必须保持机器可读，并正确报告未完成的任务。"""

import json
import sys
from types import SimpleNamespace

import pytest

from minicode import cli, mcp_client, session


@pytest.mark.parametrize("output_format", ["json", "stream-json"])
def test_json_run_reports_loop_limit_without_terminal_noise(tmp_path, monkeypatch, capsys, output_format):
    class FakeAgent:
        def __init__(self, **_kwargs):
            self.messages = []
            self.context = SimpleNamespace(cumulative_tokens=12)
            self.last_stop_reason = "loop_limit"
            self.on_compact = None
            self.on_tool_result = None

        def run_turn(self, _prompt, on_text=None):
            if self.on_compact:
                self.on_compact(4, 2)
            return "未完成"

    monkeypatch.setattr(cli, "Agent", FakeAgent)
    monkeypatch.setattr(mcp_client, "load_mcp_tools", lambda **_kwargs: [])
    monkeypatch.setattr(session, "SESSION_DIR", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["minicode", "-p", "任务", "--output-format", output_format])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == (2 if output_format == "stream-json" else 1)
    if output_format == "stream-json":
        assert json.loads(lines[0])["type"] == "compaction"
    result = json.loads(lines[-1])
    assert result.get("status") == "incomplete", result
    assert result["result"] == "未完成"
    assert result["usage_tokens"] == 12


@pytest.mark.parametrize("output_format", ["json", "stream-json"])
def test_headless_mcp_auth_error_is_machine_readable(monkeypatch, capsys, output_format):
    def fail_mcp(**_kwargs):
        raise PermissionError("非交互运行无法完成 MCP OAuth 登录")

    monkeypatch.setattr(mcp_client, "load_mcp_tools", fail_mcp)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["minicode", "-p", "任务", "--output-format", output_format])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    event = json.loads(capsys.readouterr().out.strip())
    assert "OAuth" in event["error"]
    assert event.get("type") == ("error" if output_format == "stream-json" else None)
