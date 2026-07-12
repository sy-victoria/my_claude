"""工具注册表。

TOOLS 是发给模型的工具 schema 列表的来源（agent.py 里 `t.to_api_schema()`
遍历它）；get_tool(name) 供 agent 循环执行工具调用时按名字查找。
"""

from minicode.tools.base import Tool
from minicode.tools.bash import bash_tool
from minicode.tools.edit_file import edit_file_tool
from minicode.tools.glob_files import glob_tool
from minicode.tools.grep_files import grep_tool
from minicode.tools.list_files import list_files_tool
from minicode.tools.read_file import read_file_tool
from minicode.tools.skill import skill_tool
from minicode.tools.task import task_tool
from minicode.tools.write_file import write_file_tool

TOOLS: list[Tool] = [
    read_file_tool,
    list_files_tool,
    glob_tool,
    grep_tool,
    edit_file_tool,
    write_file_tool,
    bash_tool,
    task_tool,
    skill_tool,
]

_TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def get_tool(name: str) -> Tool | None:
    return _TOOLS_BY_NAME.get(name)
