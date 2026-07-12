"""grep 工具：用正则搜索文件内容，返回 `文件:行号:内容`。

这是在真实代码库里干活最重要的工具之一：改一个函数前先 grep 它被谁引用、
排查报错时先 grep 错误信息出现在哪。返回格式带行号，方便模型下一步
read_file 时直接定位。
"""

import re
from pathlib import Path

from minicode.tools.base import Tool
from minicode.tools.glob_files import _is_ignored

MAX_MATCHES = 50
MAX_LINE_CHARS = 200


def _run(tool_input: dict) -> str:
    pattern = tool_input["pattern"]
    root = Path(tool_input.get("path") or ".")
    file_glob = tool_input.get("glob") or "**/*"

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"错误：正则表达式无效：{exc}。请修正 pattern 后重试。"
    if not root.is_dir():
        return f"错误：目录不存在：{root}"

    matches: list[str] = []
    for path in sorted(root.glob(file_glob)):
        if not path.is_file() or _is_ignored(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 跳过二进制/不可读文件，而不是让整次搜索失败
        for line_no, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                matches.append(f"{path}:{line_no}:{line.strip()[:MAX_LINE_CHARS]}")
                if len(matches) >= MAX_MATCHES:
                    matches.append("[... 匹配过多已截断，请用更精确的 pattern 或 glob 缩小范围]")
                    return "\n".join(matches)

    if not matches:
        return f"没有找到匹配 {pattern!r} 的内容。"
    return "\n".join(matches)


grep_tool = Tool(
    name="grep",
    description=(
        "用正则表达式搜索文件内容，返回 `文件路径:行号:该行内容`。"
        "可用 glob 参数限定搜索的文件范围（如 **/*.py）。"
        "重命名/修改一个函数前，先用我找出它的定义和所有引用位置；"
        "找文件名用 glob，看完整文件内容用 read_file。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "搜索根目录，默认当前工作目录"},
            "glob": {"type": "string", "description": "限定文件范围的 glob 模式，如 **/*.py"},
        },
        "required": ["pattern"],
    },
    run=_run,
)
