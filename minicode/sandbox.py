"""隔离本地工具进程：Linux 使用 bubblewrap，Windows 使用本地 Docker。"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def uses_docker() -> bool:
    return os.name == "nt" or platform.system() == "Darwin"


def sandbox_argv(argv: list[str], cwd: Path | None = None,
                 writable_workspace: bool = True,
                 extra_env: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
    """构造无网络、仅工作区可写的进程；缺少隔离能力时拒绝执行。"""
    workspace = (cwd or Path.cwd()).resolve()
    if uses_docker():
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("当前平台需要本地 Docker 沙箱，拒绝执行本地进程")
        image = os.environ.get("MINICODE_SANDBOX_IMAGE", "python:3.11.11-slim-bookworm")
        if not image or image.startswith("-"):
            raise RuntimeError("无效的 MINICODE_SANDBOX_IMAGE")
        mount = f"type=bind,source={workspace},target=/workspace"
        package_root = Path(__file__).resolve().parent.parent
        package_mount = f"type=bind,source={package_root},target=/opt/minicode,readonly"
        if not writable_workspace:
            mount += ",readonly"
        mapped_argv: list[str] = []
        for index, argument in enumerate(argv):
            if index == 0 and Path(argument).resolve() == Path(sys.executable).resolve():
                mapped_argv.append("python3")
            elif Path(argument).is_absolute() and Path(argument).resolve().is_relative_to(workspace):
                relative = Path(argument).resolve().relative_to(workspace)
                mapped_argv.append("/workspace/" + relative.as_posix())
            elif Path(argument).is_absolute() and Path(argument).resolve().is_relative_to(package_root):
                relative = Path(argument).resolve().relative_to(package_root)
                mapped_argv.append("/opt/minicode/" + relative.as_posix())
            else:
                mapped_argv.append(argument)
        container_name = "minicode-" + uuid.uuid4().hex[:16]
        command = [docker, "run", "--rm", "--name", container_name,
                   "--pull", "never", "--network", "none",
                   "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                   "--pids-limit", "128", "--memory", "512m", "--user", "65534:65534",
                   "--tmpfs", "/tmp:rw,nosuid,nodev", "--mount", mount,
                   "--mount", package_mount, "--env", "PYTHONPATH=/opt/minicode",
                   "--workdir", "/workspace", "-i"]
        for key, value in (extra_env or {}).items():
            command.extend(["--env", f"{key}={value}"])
        command.extend([image, *mapped_argv])
        return command, os.environ.copy()
    if os.name != "posix" or not Path("/proc/self/ns/user").exists():
        raise RuntimeError("当前平台尚无系统级沙箱，拒绝执行本地进程")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("未安装 bubblewrap，拒绝执行本地进程")
    if workspace == Path("/"):
        raise RuntimeError("不能把根目录作为可写工作区")
    path_env = os.environ.get("PATH", "/usr/bin:/bin")
    args = [bwrap, "--die-with-parent", "--unshare-all", "--new-session",
            "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp"]
    # 覆盖用户目录，避免项目中的命令读取同级目录下的密钥。
    for directory in ("/home", "/root"):
        if Path(directory).is_dir():
            args += ["--tmpfs", directory]
    if any(workspace.is_relative_to(Path(directory)) for directory in ("/home", "/root", "/tmp")):
        args += ["--dir", str(workspace.parent)]
    args += ["--bind" if writable_workspace else "--ro-bind", str(workspace), str(workspace),
             "--dir", "/tmp/minicode", "--ro-bind", str(Path(__file__).resolve().parent.parent), "/tmp/minicode",
             "--chdir", str(workspace),
             "--clearenv", "--setenv", "PATH", path_env,
             "--setenv", "HOME", "/tmp", "--setenv", "PYTHONPATH", "/tmp/minicode"]
    for key, value in (extra_env or {}).items():
        args += ["--setenv", key, value]
    args += ["--", *argv]
    return args, {"PATH": path_env}


def sandbox_command(command: str, cwd: Path | None = None,
                    writable_workspace: bool = True,
                    extra_env: dict[str, str] | None = None) -> tuple[list[str], dict[str, str]]:
    return sandbox_argv(["/bin/sh", "-c", command], cwd, writable_workspace, extra_env)


def stop_sandbox(argv: list[str], env: dict[str, str]) -> None:
    """Docker CLI 被超时中断时，删除它启动的那个临时容器。"""
    if not uses_docker() or "--name" not in argv:
        return
    name = argv[argv.index("--name") + 1]
    if not name.startswith("minicode-"):
        return
    try:
        subprocess.run([argv[0], "rm", "-f", name], env=env, capture_output=True,
                       timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
