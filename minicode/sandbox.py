"""在 Linux 上用 bubblewrap 隔离本地工具进程。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def sandbox_argv(argv: list[str], cwd: Path | None = None,
                 writable_workspace: bool = True) -> tuple[list[str], dict[str, str]]:
    """构造无网络、仅工作区可写的进程；缺少隔离能力时拒绝执行。"""
    if os.name != "posix" or not Path("/proc/self/ns/user").exists():
        raise RuntimeError("当前平台尚无系统级沙箱，拒绝执行本地进程")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("未安装 bubblewrap，拒绝执行本地进程")
    workspace = (cwd or Path.cwd()).resolve()
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
    if workspace.is_relative_to(Path("/home")) or workspace.is_relative_to(Path("/root")):
        args += ["--dir", str(workspace.parent)]
    args += ["--bind" if writable_workspace else "--ro-bind", str(workspace), str(workspace),
             "--chdir", str(workspace),
             "--clearenv", "--setenv", "PATH", path_env,
             "--setenv", "HOME", "/tmp", "--", *argv]
    return args, {"PATH": path_env}


def sandbox_command(command: str, cwd: Path | None = None,
                    writable_workspace: bool = True) -> tuple[list[str], dict[str, str]]:
    return sandbox_argv(["/bin/sh", "-c", command], cwd, writable_workspace)
