"""测试/验收用的迷你 MCP server：提供一个 add 工具。

实现了 stdio 传输 + MCP 最小方法集（initialize / tools/list / tools/call），
也是一份"MCP server 长什么样"的教学示例——整个协议的骨架就这么大。
用法：python3 mini_mcp_server.py（等待 stdin 上的 JSON-RPC 消息）
"""

import json
import sys

TOOLS = [
    {
        "name": "add",
        "description": "计算两个数字的和",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    }
]


def handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mini-calc", "version": "0.1.0"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        if params["name"] == "add":
            total = params["arguments"]["a"] + params["arguments"]["b"]
            return {"content": [{"type": "text", "text": str(total)}]}
        return {"content": [{"type": "text", "text": "未知工具"}], "isError": True}
    return {}


def main() -> None:
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("id") is None:
            continue  # 通知不需要响应
        result = handle(message.get("method", ""), message.get("params", {}))
        response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
