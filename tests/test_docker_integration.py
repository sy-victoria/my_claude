"""Windows Docker 沙箱的实际文件、网络和只读挂载验收。"""

import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from minicode.agent import Agent
from minicode.permissions import PermissionManager
from minicode.sandbox import sandbox_argv, sandbox_command

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.environ.get("MINICODE_TEST_DOCKER") != "1",
    reason="需要在 Windows 上显式启用 Docker 集成测试",
)


def test_file_tools_inside_docker():
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        target = Path(directory) / "probe.txt"
        agent = Agent(client=SimpleNamespace(create=lambda **_kwargs: None),
                      permissions=PermissionManager(mode="yolo", cwd=Path.cwd()))
        agent._run_tool("write_file", {"path": str(target), "content": "sandbox-file-ok"})
        assert target.read_text(encoding="utf-8") == "sandbox-file-ok"
        assert "sandbox-file-ok" in agent._run_tool("read_file", {"path": str(target)})


def test_readonly_mount_rejects_write():
    argv, env = sandbox_argv(["/bin/sh", "-c", "touch /workspace/should-not-exist"],
                             writable_workspace=False)
    proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=25)
    assert proc.returncode != 0
    assert not Path("should-not-exist").exists()


def test_network_namespace_has_no_external_route():
    command = "python3 -c 'import socket; s=socket.socket(); s.settimeout(1); s.connect((\"1.1.1.1\",53))'"
    argv, env = sandbox_command(command)
    proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=25)
    assert proc.returncode != 0
