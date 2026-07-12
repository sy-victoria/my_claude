"""list_files 工具：列出目录下的文件和子目录（不递归）。"""

from pathlib import Path

from minicode.tools.base import Tool


def _run(tool_input: dict) -> str:
    path = tool_input.get("path") or "."
    p = Path(path)

    if not p.exists():
        return f"错误：路径不存在：{path}"
    if not p.is_dir():
        return f"错误：{path} 不是目录，请用 read_file 读取文件内容"

    entries = sorted(p.iterdir(), key=lambda e: e.name)
    if not entries:
        return "（空目录）"

    # 目录名加 `/` 后缀，模型不需要额外调用就能分辨文件和目录。
    names = [e.name + "/" if e.is_dir() else e.name for e in entries]
    return "\n".join(names)


list_files_tool = Tool(
    name="list_files",
    description=(
        "列出指定目录下的文件和子目录（只列一层，不递归）。目录名会带 `/` 后缀。"
        "path 不传时默认列出当前工作目录。想知道某个目录里有什么、或确认某个"
        "文件是否存在时，优先用这个工具而不是凭猜测调用 read_file。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要列出的目录路径，默认为当前工作目录"},
        },
        "required": [],
    },
    run=_run,
)
