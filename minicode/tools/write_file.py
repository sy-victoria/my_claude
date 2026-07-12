"""write_file 工具：整文件写入。

与 edit_file 的分工：写全新文件或整体重写用我（不用受 old_str 唯一匹配的
约束）；对已有文件做局部修改用 edit_file（改动范围小、不容易误伤其他内容）。
"""

from pathlib import Path

from minicode.tools.base import Tool


def _run(tool_input: dict) -> str:
    path = tool_input["path"]
    content = tool_input["content"]
    p = Path(path)

    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    action = "已覆盖" if existed else "已创建"
    return f"{action} {path}（{len(content)} 字符）"


write_file_tool = Tool(
    name="write_file",
    description=(
        "把 content 完整写入 path（文件已存在则整体覆盖）。适合创建新文件或"
        "整体重写；只改文件中一小段时应该用 edit_file，避免意外覆盖其他内容。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "content": {"type": "string", "description": "文件的完整内容"},
        },
        "required": ["path", "content"],
    },
    run=_run,
    permission_level="write",
)
