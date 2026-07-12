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


def build_subagent_tools() -> list[Tool]:
    from minicode.tools import TOOLS  # 局部导入避免循环依赖

    return [t for t in TOOLS if t.name in SUBAGENT_TOOL_NAMES]


def _make_subagent() -> Any:
    if subagent_factory is not None:
        return subagent_factory()

    from minicode.agent import Agent  # 局部导入避免循环依赖

    return Agent(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        tools=build_subagent_tools(),
        max_loops=MAX_SUB_LOOPS,
        on_tool_call=on_subagent_tool_call,
    )


def _run(tool_input: dict) -> str:
    prompt = tool_input["prompt"]
    try:
        sub_agent = _make_subagent()
    except ValueError as exc:
        return f"错误：无法创建子 agent：{exc}"

    # 子 agent 跑完整的 agent 循环；它的几十条中间消息都留在它自己的
    # messages 里，主 agent 只收到这一段最终文本。
    return sub_agent.run_turn(prompt)


task_tool = Tool(
    name="task",
    description=(
        "把一个探索/调查类任务派给独立的子 agent 执行，返回它的调查结论。"
        "子 agent 有自己独立的上下文和只读工具（read_file/list_files/glob/grep），"
        "适合『全面调查 X 在哪里实现』『梳理某个模块的结构』这类需要大量搜索"
        "和阅读的任务——中间过程不会占用当前对话的上下文。"
        "不适合：简单的单次查找（直接用 grep 更快）、需要修改文件的任务"
        "（子 agent 没有写权限）。prompt 要写清楚调查目标和期望的输出形式。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "任务的一句话概述（给用户看的进度提示）"},
            "prompt": {"type": "string", "description": "给子 agent 的完整任务指令，包含调查目标和期望输出"},
        },
        "required": ["description", "prompt"],
    },
    run=_run,
)
