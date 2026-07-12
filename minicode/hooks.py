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
) -> tuple[bool, str]:
    """运行匹配的 hook。返回 (是否放行, 阻止理由)。

    只有 pre_tool 事件的非零退出才产生 (False, 理由)；其他情况都放行。
    """
    for hook in hooks.get(event, []):
        if hook.get("tool") not in (None, tool_name):
            continue
        env = os.environ.copy()
        env["TOOL_NAME"] = tool_name
        env["TOOL_INPUT"] = json.dumps(tool_input, ensure_ascii=False)
        env["TOOL_FILE"] = str(tool_input.get("path", ""))
        try:
            proc = subprocess.run(
                hook["command"],
                shell=True,
                capture_output=True,
                text=True,
                timeout=HOOK_TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            if event == "pre_tool":
                return False, f"pre_tool hook 超时（{HOOK_TIMEOUT_SECONDS}s）：{hook['command']}"
            continue
        if event == "pre_tool" and proc.returncode != 0:
            reason = (proc.stderr or proc.stdout or "").strip() or "（hook 未输出理由）"
            return False, reason
    return True, ""
