"""read_file 工具：读取文件内容，带行号返回。

为什么带行号：模仿 Claude Code 的 Read 工具。行号方便模型在后续对话里精确
引用某一行，也方便 edit_file 时判断要替换的内容在文件的哪个位置。
"""

from pathlib import Path

from minicode import config
from minicode.tools.base import Tool


def _run(tool_input: dict) -> str:
    path = tool_input["path"]
    offset = int(tool_input.get("offset") or 1)  # 1-based 起始行号
    limit = int(tool_input.get("limit") or config.READ_MAX_LINES)
    p = Path(path)

    if not p.exists():
        return f"错误：文件不存在：{path}"
    if p.is_dir():
        return f"错误：{path} 是一个目录，不是文件，请用 list_files 查看目录内容"

    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"错误：{path} 不是可读的文本文件（UTF-8 解码失败）"

    if text == "":
        return "（空文件）"

    lines = text.splitlines()
    total = len(lines)
    window = lines[offset - 1 : offset - 1 + limit]
    if not window:
        return f"错误：offset={offset} 超出文件范围（共 {total} 行）"

    body = "\n".join(f"{offset + i}\t{line}" for i, line in enumerate(window))
    shown_end = offset + len(window) - 1
    if offset > 1 or shown_end < total:
        # 分页提示也是给模型的导航信息：告诉它还有哪些部分没读、怎么读。
        body += f"\n[文件共 {total} 行，本次显示第 {offset}~{shown_end} 行；其余部分用 offset/limit 参数读取]"
    return body


read_file_tool = Tool(
    name="read_file",
    description=(
        "读取指定路径文件的内容，返回带行号的文本（格式：`行号<TAB>内容`）。"
        "在用 edit_file 编辑一个文件之前，必须先用这个工具读取它的当前内容，"
        "确保后续的替换文本与文件实际内容完全一致。"
        "path 可以是相对当前工作目录的路径，也可以是绝对路径。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要读取的文件路径"},
            "offset": {"type": "integer", "description": "起始行号（1-based），默认 1；用于分页读取大文件"},
            "limit": {"type": "integer", "description": "最多读取的行数，默认 500"},
        },
        "required": ["path"],
    },
    run=_run,
)
