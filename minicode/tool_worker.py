"""文件工具的隔离子进程入口：只接受白名单工具与一条 JSON 请求。"""

import json
import sys

from minicode.tools import get_tool

FILE_TOOL_NAMES = {"read_file", "list_files", "glob", "grep", "edit_file", "write_file"}


def main() -> None:
    try:
        request = json.load(sys.stdin)
        name = request["name"]
        if name not in FILE_TOOL_NAMES:
            raise ValueError(f"不允许在文件工具子进程中执行 {name}")
        tool = get_tool(name)
        assert tool is not None
        result = tool.run(request["input"])
        print(json.dumps({"result": result}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
