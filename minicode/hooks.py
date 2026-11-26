"""hooks：在工具执行前后运行用户配置的 shell 命令（复现 Claude Code 的 hooks）。

hooks 解决的问题是"确定性的自动化"：有些事你希望**每次都发生**（编辑后
自动格式化、执行前记日志/做校验），交给提示词模型可能忘，写成 hook 就是
机制保证——这和 M5"读后编辑约束"的哲学一脉相承：能用机制保证的不靠提示词。

配置文件 `.minicode/hooks.json`：
    {
      "pre_tool":  [{"tool": "bash", "command": "echo $TOOL_INPUT >> audit.log"}],
      "post_tool": [{"tool": "edit_file", "command": "black $TOOL_FILE 2>/dev/null"}]
    }

约定：
    - `tool` 省略时匹配所有工具
    - hook 通过环境变量拿到上下文：TOOL_NAME、TOOL_INPUT（JSON）、
      TOOL_FILE（输入里的 path 字段，若有）
    - **pre_tool hook 非零退出会阻止工具执行**，stderr/stdout 作为阻止理由
      喂回模型；post_tool 的失败只提示不阻断（事后无法"撤销"工具效果）
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from minicode.sandbox import sandbox_command, stop_sandbox, uses_docker

HOOK_TIMEOUT_SECONDS = 10


def load_hooks(cwd: Path | None = None) -> dict[str, list[dict[str, str]]]:
    cwd = cwd or Path.cwd()
    config_file = cwd / ".minicode" / "hooks.json"
    if not config_file.is_file():
        return {}
    return json.loads(config_file.read_text(encoding="utf-8"))


def run_hooks(
    hooks: dict[str, list[dict[str, str]]],
    event: str,
    tool_name: str,
    tool_input: dict[str, Any],
    cwd: Path | None = None,
) -> tuple[bool, str]:
    """运行匹配的 hook。返回 (是否放行, 阻止理由)。

    只有 pre_tool 事件的非零退出才产生 (False, 理由)；其他情况都放行。
    """
    for hook in hooks.get(event, []):
        if hook.get("tool") not in (None, tool_name):
            continue
        env = os.environ.copy()
        env["TOOL_NAME"] = tool_name
        hook_input = dict(tool_input)
        hook_path = str(tool_input.get("path", ""))
        if uses_docker() and cwd is not None and hook_path:
            target = (cwd / hook_path).resolve()
            if target.is_relative_to(cwd.resolve()):
                hook_path = "/workspace/" + target.relative_to(cwd.resolve()).as_posix()
                hook_input["path"] = hook_path
        env["TOOL_INPUT"] = json.dumps(hook_input, ensure_ascii=False)
        env["TOOL_FILE"] = hook_path
        try:
            # 只读工具的 hook 不能借由自动执行获得工作区写权限。
            writable = tool_name in {"bash", "edit_file", "write_file"} or tool_name.startswith("mcp__")
            argv, sandbox_env = sandbox_command(
                hook["command"], cwd=cwd, writable_workspace=writable,
                extra_env={key: env[key] for key in ("TOOL_NAME", "TOOL_INPUT", "TOOL_FILE")},
            )
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=HOOK_TIMEOUT_SECONDS,
                env=sandbox_env,
            )
        except RuntimeError as exc:
            if event == "pre_tool":
                return False, str(exc)
            continue
        except subprocess.TimeoutExpired:
            stop_sandbox(argv, sandbox_env)
            if event == "pre_tool":
                return False, f"pre_tool hook 超时（{HOOK_TIMEOUT_SECONDS}s）：{hook['command']}"
            continue
        if event == "pre_tool" and proc.returncode != 0:
            reason = (proc.stderr or proc.stdout or "").strip() or "（hook 未输出理由）"
            return False, reason
    return True, ""
