"""沙箱命令必须明确限制网络、权限与挂载。"""

import os
import sys
from pathlib import Path

import pytest

from minicode.sandbox import sandbox_command


@pytest.mark.skipif(os.name != "nt", reason="Windows Docker 后端")
def test_windows_docker_command_has_isolation_flags(tmp_path, monkeypatch):
    monkeypatch.setattr("minicode.sandbox.shutil.which", lambda name: "docker.exe")
    argv, _ = sandbox_command("echo hello", cwd=tmp_path)
    assert argv[:3] == ["docker.exe", "run", "--rm"]
    assert argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--mount") + 1].startswith(f"type=bind,source={tmp_path}")
    assert argv[-3:] == ["/bin/sh", "-c", "echo hello"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Docker 后端")
def test_windows_local_mcp_mount_is_readonly(tmp_path, monkeypatch):
    monkeypatch.setattr("minicode.sandbox.shutil.which", lambda name: "docker.exe")
    from minicode.sandbox import sandbox_argv
    argv, _ = sandbox_argv(["python3", "server.py"], cwd=Path(tmp_path), writable_workspace=False)
    assert argv[argv.index("--mount") + 1].endswith(",readonly")


@pytest.mark.skipif(os.name != "nt", reason="Windows Docker 后端")
def test_windows_python_and_project_paths_are_mapped(tmp_path, monkeypatch):
    monkeypatch.setattr("minicode.sandbox.shutil.which", lambda name: "docker.exe")
    from minicode.sandbox import sandbox_argv
    script = tmp_path / "server.py"
    argv, _ = sandbox_argv([sys.executable, str(script)], cwd=tmp_path)
    assert argv[-2:] == ["python3", "/workspace/server.py"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Docker 后端")
def test_timeout_cleanup_targets_only_generated_container(tmp_path, monkeypatch):
    from minicode.sandbox import stop_sandbox
    monkeypatch.setattr("minicode.sandbox.shutil.which", lambda name: "docker.exe")
    argv, env = sandbox_command("sleep 30", cwd=tmp_path)
    seen = []
    monkeypatch.setattr("minicode.sandbox.subprocess.run", lambda command, **_kwargs: seen.append(command))
    stop_sandbox(argv, env)
    assert seen == [["docker.exe", "rm", "-f", argv[argv.index("--name") + 1]]]
