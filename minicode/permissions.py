"""按操作范围审批工具调用；拒绝规则优先于交互确认。"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Callable

from minicode.tools.base import Tool

MODES = ("default", "accept-edits", "yolo")
AskUserFn = Callable[[str, dict[str, Any]], str]
FILE_TOOLS = {"read_file", "list_files", "glob", "grep", "edit_file", "write_file"}
WRITE_TOOLS = {"edit_file", "write_file"}


def _terminal_ask(tool_name: str, tool_input: dict[str, Any]) -> str:
    print(f"\n  ! agent 请求调用：{tool_name}({tool_input})")
    return input("  允许吗？[y=本次 / a=本会话相同操作 / n=拒绝] ").strip().lower()


def decide(mode: str, level: str, in_allowlist: bool) -> str:
    """保留旧决策接口，供已有调用者和测试使用。"""
    if in_allowlist or mode == "yolo" or level == "read":
        return "allow"
    if mode == "accept-edits" and level == "write":
        return "allow"
    return "ask"


def _rule_matches(rule: str, tool: Tool, target: str) -> bool:
    name, sep, pattern = rule.partition(":")
    return name == tool.name and (not sep or fnmatch.fnmatchcase(target, pattern))


class PermissionManager:
    def __init__(
        self,
        mode: str = "default",
        ask_user: AskUserFn | None = None,
        cwd: Path | None = None,
        rules: dict[str, list[str]] | None = None,
        additional_read_dirs: list[Path] | None = None,
        additional_write_dirs: list[Path] | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"未知权限模式 {mode!r}，可选：{', '.join(MODES)}")
        self.mode = mode
        self.ask_user = ask_user or _terminal_ask
        self.cwd = (cwd or Path.cwd()).resolve()
        self.rules = rules or {}
        self.read_roots = [self.cwd, *(p.resolve() for p in additional_read_dirs or [])]
        self.write_roots = [self.cwd, *(p.resolve() for p in additional_write_dirs or [])]
        self._session_allowlist: set[str] = set()

    def _target(self, tool: Tool, tool_input: dict[str, Any]) -> tuple[str, Path | None]:
        if tool.name in FILE_TOOLS:
            path = (self.cwd / tool_input.get("path", ".")).resolve()
            return str(path), path
        if tool.name == "bash":
            return str(tool_input.get("command", "")), None
        return json.dumps(tool_input, sort_keys=True, ensure_ascii=False), None

    def check(self, tool: Tool, tool_input: dict[str, Any]) -> tuple[bool, str]:
        try:
            target, path = self._target(tool, tool_input)
        except (TypeError, ValueError, OSError) as exc:
            return False, f"权限拒绝：无效工具参数：{exc}"
        if path is not None:
            roots = self.write_roots if tool.name in WRITE_TOOLS else self.read_roots
            if not any(path.is_relative_to(root) for root in roots):
                return False, f"权限拒绝：{path} 不在允许的工作目录内"
        if any(_rule_matches(r, tool, target) for r in self.rules.get("deny", [])):
            return False, f"权限拒绝：{tool.name}({target}) 命中 deny 规则"
        if any(_rule_matches(r, tool, target) for r in self.rules.get("ask", [])):
            verdict = "ask"
        elif any((r == f"bash:{target}" if tool.name == "bash" else _rule_matches(r, tool, target))
                 for r in self.rules.get("allow", [])):
            verdict = "allow"
        else:
            verdict = decide(self.mode, tool.permission_level, f"{tool.name}:{target}" in self._session_allowlist)
        if verdict == "allow":
            return True, ""
        answer = self.ask_user(tool.name, tool_input)
        if answer == "a":
            self._session_allowlist.add(f"{tool.name}:{target}")
            return True, ""
        if answer == "y":
            return True, ""
        return False, f"用户拒绝了本次 {tool.name} 调用。请不要原样重试。"
