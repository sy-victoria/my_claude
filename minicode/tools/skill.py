"""skill 工具：模型自主触发 skill 的通道。

skill 有两条触发路径（对应 Claude Code 的设计）：
    1. 用户触发：在 CLI 输入 /名字 参数（cli.py 处理）
    2. 模型触发：模型从 system prompt 的 skill 清单里判断"当前任务该用
       某个 skill"，调用本工具拿到正文——这就是渐进式披露的"翻书"动作

工具返回的是 skill 正文（一段操作指引），模型读完后按指引行动。
"""

from minicode.skills import discover_skills, render_skill
from minicode.tools.base import Tool


def _run(tool_input: dict) -> str:
    name = tool_input["name"]
    skills = discover_skills()
    skill = skills.get(name)
    if skill is None:
        available = ", ".join(skills) or "（无）"
        return f"错误：没有名为 {name!r} 的 skill。当前可用：{available}"
    return f"[skill {name} 的操作指引]\n{render_skill(skill)}"


skill_tool = Tool(
    name="skill",
    description=(
        "加载一个 skill（预定义的操作指引）的完整内容。system prompt 里的"
        "『可用技能清单』列出了每个 skill 的用途；当用户的任务匹配某个 skill "
        "的用途时，先用本工具加载它的指引，再按指引执行。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "skill 的名字（见 system prompt 的清单）"},
        },
        "required": ["name"],
    },
    run=_run,
)
