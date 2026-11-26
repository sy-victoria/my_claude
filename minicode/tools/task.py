"""task 工具：把探索型任务派给独立上下文的子 agent（复现 Claude Code 的 Task）。

子 agent 的本质是**用 API 花费换主上下文空间**：搜索类任务（"全项目找 X"）
会产生几十次 grep/read 的中间输出，全塞进主对话会污染上下文；派给一个
全新消息列表的子 agent，它在自己的上下文里翻箱倒柜，只把最终结论一段话
带回来。

两条铁律（防失控）：
    1. 子 agent 的工具集不含 task ——不能再派生子 agent（防递归爆炸）；
    2. 子 agent 有最大循环轮数限制（MAX_SUB_LOOPS）。

子 agent 只给只读工具：探索任务不需要写权限，这也让 task 工具自身可以
安全地声明为 read 级（整条链路都改不了任何东西）。
"""

import os
from contextvars import ContextVar
from typing import Any, Callable

from minicode.tools.base import Tool

# 子 agent 可用的工具（只读子集，不含 task 自身）
SUBAGENT_TOOL_NAMES = {"read_file", "list_files", "glob", "grep"}
MAX_SUB_LOOPS = 15

# 子 agent 工具调用的显示钩子（CLI 用缩进前缀区分主/子 agent 的动作）
on_subagent_tool_call: Callable[[str, dict[str, Any]], None] = lambda name, tool_input: print(
    f"      >> [sub] {name}({str(tool_input)[:100]})"
)

# 测试注入点：设置后 _run 用它构造子 agent，替代真实 API。
subagent_factory: Callable[[], Any] | None = None
current_parent: ContextVar[Any | None] = ContextVar("minicode_task_parent", default=None)


def build_subagent_tools(mode: str = "explore") -> list[Tool]:
    from minicode.tools import TOOLS  # 局部导入避免循环依赖

    if mode == "work":
        return [t for t in TOOLS if t.name not in {"task", "todo_write"}]
    return [t for t in TOOLS if t.name in SUBAGENT_TOOL_NAMES]


def _make_subagent(mode: str = "explore", max_loops: int = MAX_SUB_LOOPS) -> Any:
    if subagent_factory is not None:
        return subagent_factory()

    from minicode.agent import Agent  # 局部导入避免循环依赖
    from minicode.permissions import PermissionManager
    from minicode.settings import load_settings
    parent = current_parent.get()

    return Agent(
        api_key=parent.api_key if parent is not None else os.environ.get("ANTHROPIC_API_KEY"),
        tier=parent.tier if parent is not None else "sonnet",
        model=parent.model if parent is not None else None,
        base_url=parent.base_url if parent is not None else None,
        tools=build_subagent_tools(mode),
        max_loops=max_loops,
        api_timeout_seconds=parent.api_timeout_seconds if parent is not None else 90,
        max_turn_seconds=parent.max_turn_seconds if parent is not None else 600,
        max_tool_calls=parent.max_tool_calls if parent is not None else 100,
        on_tool_call=on_subagent_tool_call,
        permissions=PermissionManager(mode="default", cwd=parent.permissions.cwd if parent is not None else None,
                                      rules=parent.permissions.rules if parent is not None else load_settings()["permissions"],
                                      ask_user=parent.permissions.ask_user if parent is not None else None),
    )


def _run(tool_input: dict) -> str:
    prompt = tool_input["prompt"]
    mode = tool_input.get("mode", "explore")
    if mode not in ("explore", "work"):
        return "错误：mode 必须是 explore 或 work"
    max_loops = tool_input.get("max_loops", MAX_SUB_LOOPS)
    if not isinstance(max_loops, int) or not 1 <= max_loops <= 30:
        return "错误：max_loops 必须在 1 到 30 之间"
    try:
        sub_agent = _make_subagent(mode, max_loops)
    except ValueError as exc:
        return f"错误：无法创建子 agent：{exc}"

    # 子 agent 跑完整的 agent 循环；它的几十条中间消息都留在它自己的
    # messages 里，主 agent 只收到这一段最终文本。
    return sub_agent.run_turn(prompt)


task_tool = Tool(
    name="task",
    description=(
        "把任务派给独立上下文的子 agent，返回其结论。"
        "默认 mode=explore 只读；mode=work 时可申请修改文件和执行命令。"
        "适合需要大量搜索或独立处理的任务；简单查找请直接用 grep。"
        "prompt 要写清楚目标和期望的输出形式。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "任务的一句话概述（给用户看的进度提示）"},
            "prompt": {"type": "string", "description": "给子 agent 的完整任务指令，包含调查目标和期望输出"},
            "mode": {"type": "string", "enum": ["explore", "work"], "description": "explore 只读；work 可申请修改与执行权限"},
            "max_loops": {"type": "integer", "minimum": 1, "maximum": 30},
        },
        "required": ["description", "prompt"],
    },
    run=_run,
)
