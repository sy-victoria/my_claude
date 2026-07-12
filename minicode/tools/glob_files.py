"""glob 工具：按文件名模式找文件。

和 grep 的分工（工具箱的"正交性"设计）：知道文件名长什么样用 glob，
知道文件内容里有什么用 grep。按修改时间倒序返回——最近改过的文件
通常和当前任务最相关，这是 Claude Code Glob 工具的同款设计。
"""

from pathlib import Path

from minicode.tools.base import Tool

MAX_RESULTS = 50
# 这些目录里的匹配结果几乎永远是噪音（依赖、缓存、版本库内部文件），
# 直接过滤掉，省上下文也省模型的注意力。
IGNORED_PARTS = {".git", ".venv", "__pycache__", "node_modules"}


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_PARTS for part in path.parts)


def _run(tool_input: dict) -> str:
    pattern = tool_input["pattern"]
    root = Path(tool_input.get("path") or ".")

    if not root.is_dir():
        return f"错误：目录不存在：{root}"

    matches = [p for p in root.glob(pattern) if p.is_file() and not _is_ignored(p)]
    if not matches:
        return f"没有匹配 {pattern!r} 的文件。可以试试更宽的模式（如 **/*.py）。"

    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    truncated = len(matches) > MAX_RESULTS
    lines = [str(p) for p in matches[:MAX_RESULTS]]
    if truncated:
        lines.append(f"[... 还有 {len(matches) - MAX_RESULTS} 个结果被省略，请用更精确的模式]")
    return "\n".join(lines)


glob_tool = Tool(
    name="glob",
    description=(
        "按文件名模式查找文件，返回匹配的路径列表（按修改时间倒序，最近改过的在前）。"
        "模式支持 * 和 **，例如 `**/*.py`（所有 Python 文件）、`src/**/test_*.py`。"
        "找『名字长什么样』的文件用我；找『内容里有什么』的文件用 grep；"
        "已经知道确切路径时直接用 read_file。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
            "path": {"type": "string", "description": "搜索的根目录，默认当前工作目录"},
        },
        "required": ["pattern"],
    },
    run=_run,
)
