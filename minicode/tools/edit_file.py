"""edit_file 工具：把文件中的 old_str 精确替换为 new_str。

两条设计要点（对应 docs/00-roadmap.md M1）：
    1. old_str 为空字符串且文件不存在 => 创建新文件，内容为 new_str。
    2. old_str 必须在文件里唯一匹配。匹配不到或匹配到多处都不能瞎猜，而是要
       返回一句对模型有指导意义的错误信息——错误信息也是 prompt 的一部分，
       模型看懂错误后会自己调整 old_str 再试一次，这比在本地"猜"更可靠。
"""

from pathlib import Path

from minicode.tools.base import Tool


def _run(tool_input: dict) -> str:
    path = tool_input["path"]
    old_str = tool_input.get("old_str", "")
    new_str = tool_input.get("new_str", "")
    p = Path(path)

    if old_str == "":
        if p.exists():
            return f"错误：{path} 已存在，old_str 不能为空（这会被当成创建新文件）。请提供要替换的原文本。"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_str, encoding="utf-8")
        return f"已创建新文件 {path}"

    if not p.exists():
        return f"错误：文件不存在：{path}。如果要创建新文件，old_str 需要传空字符串。"

    text = p.read_text(encoding="utf-8")
    count = text.count(old_str)

    if count == 0:
        return (
            f"错误：在 {path} 中找不到匹配的 old_str。"
            "请用 read_file 重新读取文件的当前内容，确认 old_str 与文件内容"
            "（包括空白字符和缩进）完全一致。"
        )
    if count > 1:
        return (
            f"错误：old_str 在 {path} 中匹配到 {count} 处，不唯一，无法确定要替换哪一处。"
            "请在 old_str 里加入更多上下文（比如前后相邻的行），使其唯一匹配。"
        )

    new_text = text.replace(old_str, new_str, 1)
    p.write_text(new_text, encoding="utf-8")
    return f"已修改 {path}"


edit_file_tool = Tool(
    name="edit_file",
    description=(
        "编辑一个已存在的文件：把 old_str 替换成 new_str。old_str 必须在文件中"
        "唯一出现——如果它出现多次或完全找不到，工具会返回错误，此时应该根据"
        "错误提示调整 old_str（通常是加入更多上下文）后重试。\n"
        "如果 old_str 传空字符串且文件不存在，会创建一个内容为 new_str 的新文件。\n"
        "编辑已存在的文件前，必须先用 read_file 读取它的当前内容。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要编辑（或创建）的文件路径"},
            "old_str": {
                "type": "string",
                "description": "要被替换的原文本，必须在文件中唯一匹配；创建新文件时传空字符串",
            },
            "new_str": {"type": "string", "description": "替换后的新文本，或新文件的完整内容"},
        },
        "required": ["path", "old_str", "new_str"],
    },
    run=_run,
)
