"""todo_write 工具：agent 的自我任务规划清单（复现 Claude Code 的 TodoWrite）。

这个工具很特别：它不操作外部世界，操作的是 agent 自己的"工作记忆"。
多步骤任务里，模型写下任务清单并逐项更新状态，作用有二：
    1. 给用户实时的进度可见性（CLI 把清单渲染出来）；
    2. 给模型自己"锚定"——长任务中每次看到清单都被提醒还剩什么没做，
       显著降低中途忘记子任务的概率（这本质上是模型的自我提示词）。
"""

from typing import Any, Callable

from minicode.tools.base import Tool

VALID_STATUSES = ("pending", "in_progress", "completed")
_STATUS_ICONS = {"pending": "☐", "in_progress": "◐", "completed": "☑"}

# 当前清单（会话级模块状态）+ 更新时的显示回调（CLI 注入渲染）
current_todos: list[dict[str, str]] = []
on_todo_update: Callable[[str], None] = lambda rendered: print(rendered)


def render(todos: list[dict[str, str]]) -> str:
    return "\n".join(f"  {_STATUS_ICONS[t['status']]} {t['content']}" for t in todos)


def _run(tool_input: dict[str, Any]) -> str:
    todos = tool_input["todos"]
    for t in todos:
        if t.get("status") not in VALID_STATUSES:
            return f"错误：status 必须是 {VALID_STATUSES} 之一，收到 {t.get('status')!r}"

    global current_todos
    current_todos = todos
    rendered = render(todos)
    on_todo_update(rendered)
    return f"任务清单已更新：\n{rendered}"


todo_tool = Tool(
    name="todo_write",
    description=(
        "维护当前任务的待办清单。适用于多步骤任务（3 步以上）：开始时列出"
        "全部步骤（status=pending），开始做某项时改为 in_progress，完成后"
        "改为 completed。每次调用传入完整的清单（覆盖式更新）。"
        "简单的单步任务不需要用。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "任务内容"},
                        "status": {"type": "string", "enum": list(VALID_STATUSES)},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    },
    run=_run,
)
