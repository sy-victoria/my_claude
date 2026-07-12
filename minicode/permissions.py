"""工具执行前的统一权限守门人。

设计思想是「策略与机制分离」：工具自己不做权限判断（M2 里 bash 曾内置
确认逻辑，本里程碑把它拆掉了），每个工具只**声明**自己的危险级别
（Tool.permission_level），放行还是询问由这里的策略统一决定。好处：

    1. 新工具不用重复实现确认逻辑，声明级别即可获得正确的权限行为；
    2. 改策略（比如加一种新模式）只动这一个文件；
    3. 测试可以脱离终端交互，直接测 decide() 这个纯函数的决策矩阵。

三种模式对应 Claude Code 的 permission modes（我们的简化版）：
    default       只读放行；写文件、执行命令要问用户
    accept-edits  写文件也放行；执行命令仍要问（对应 Claude Code 的 acceptEdits）
    yolo          全部放行（对应 bypassPermissions，启动时会警告）

用户在询问时按 `a`（always）可以把该工具加进**会话级白名单**，本会话内
不再询问——这是对 Claude Code「always allow」按钮的简化复现。
"""

from typing import Any, Callable

from minicode.tools.base import Tool

MODES = ("default", "accept-edits", "yolo")

# 询问钩子：输入工具名和参数，返回用户的选择 "y"（本次允许）/ "a"（本会话
# 始终允许）/ 其他（拒绝）。做成可注入是为了测试和非交互场景。
AskUserFn = Callable[[str, dict[str, Any]], str]


def _terminal_ask(tool_name: str, tool_input: dict[str, Any]) -> str:
    print(f"\n  ! agent 请求调用：{tool_name}({tool_input})")
    return input("  允许吗？[y=本次允许 / a=本会话始终允许 / n=拒绝] ").strip().lower()


def decide(mode: str, level: str, in_allowlist: bool) -> str:
    """纯函数的决策矩阵：返回 "allow" 或 "ask"。

    拒绝（deny）不在这里产生——本项目的简化里，deny 只来自用户在询问时
    按 n。（真实 Claude Code 还有规则配置产生的硬 deny，我们不做。）
    """
    if in_allowlist:
        return "allow"
    if mode == "yolo":
        return "allow"
    if level == "read":
        return "allow"
    if mode == "accept-edits" and level == "write":
        return "allow"
    return "ask"  # default 模式的 write/execute；accept-edits 模式的 execute


class PermissionManager:
    def __init__(self, mode: str = "default", ask_user: AskUserFn | None = None) -> None:
        if mode not in MODES:
            valid = ", ".join(MODES)
            raise ValueError(f"未知权限模式 {mode!r}，可选：{valid}")
        self.mode = mode
        self.ask_user = ask_user or _terminal_ask
        self._session_allowlist: set[str] = set()

    def check(self, tool: Tool, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """工具执行前的统一入口。返回 (是否放行, 拒绝理由)。

        拒绝理由会被 agent 作为 tool_result 喂回模型——拒绝也是对话的
        一部分，模型看到理由后通常会换一种做法或询问用户。
        """
        verdict = decide(self.mode, tool.permission_level, tool.name in self._session_allowlist)
        if verdict == "allow":
            return True, ""

        answer = self.ask_user(tool.name, tool_input)
        if answer == "a":
            self._session_allowlist.add(tool.name)
            return True, ""
        if answer == "y":
            return True, ""
        return False, (
            f"用户拒绝了本次 {tool.name} 调用。请不要原样重试；"
            "可以询问用户的顾虑，或改用其他方式完成任务。"
        )
