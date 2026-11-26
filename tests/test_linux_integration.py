"""Linux 原生 bubblewrap 端到端验收：工作区、文件、网络和本地 MCP。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from minicode.agent import Agent
from minicode.mcp_client import McpServer
from minicode.permissions import PermissionManager
from minicode.sandbox import sandbox_command


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="仅 Linux 原生 bubblewrap")


def test_linux_workspace_and_file_tools(tmp_path: Path) -> None:
    agent = Agent(client=SimpleNamespace(create=lambda **_kwargs: None),
                  permissions=PermissionManager(mode="yolo", cwd=tmp_path))
    assert "成功" in agent._run_tool("bash", {"command": "printf sandbox-ok > shell.txt"})
    assert (tmp_path / "shell.txt").read_text() == "sandbox-ok"
    assert "已创建" in agent._run_tool("write_file", {"path": "file.txt", "content": "file-ok"})
    assert "file-ok" in agent._run_tool("read_file", {"path": "file.txt"})


def test_linux_cannot_write_outside_workspace_or_use_network(tmp_path: Path) -> None:
    outside = tmp_path.parent / "sandbox-outside.txt"
    command = f"printf forbidden > {outside}"
    argv, env = sandbox_command(command, cwd=tmp_path)
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert not outside.exists()

    argv, env = sandbox_command(
        "python3 -c 'import socket; s=socket.socket(); s.settimeout(1); s.connect((\"1.1.1.1\",53))'",
        cwd=tmp_path)
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0


def test_linux_local_mcp_is_sandboxed() -> None:
    server_path = Path(__file__).with_name("mini_mcp_server.py")
    server = McpServer("calc", [sys.executable, str(server_path)])
    try:
        server.initialize()
        assert server.call_tool("add", {"a": 2, "b": 3}) == "5"
    finally:
        server.close()
