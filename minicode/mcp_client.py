"""手写的最小 MCP（Model Context Protocol）客户端。

MCP 是把外部工具接入 agent 的开放协议。我们不用官方 SDK，直接手写 stdio
传输层——教学价值最大，而且能看清协议的全貌其实很小：

    1. 启动 server 子进程，stdin/stdout 上跑 JSON-RPC 2.0（一行一条消息）
    2. `initialize` 握手 -> `notifications/initialized` 通知
    3. `tools/list` 拉取工具清单（名字/描述/inputSchema）
    4. 模型要调用时转发 `tools/call`

拉到的远程工具被包装成我们自己的 Tool 协议（base.py）混入注册表——
**agent 循环对"本地工具"和"MCP 工具"一视同仁，零改动**。这正是 M1 工具层
抽象的回报：能力的来源（本地函数 or 远程进程）是工具层的实现细节。

注意：DeepSeek 端点不支持服务端 MCP，但这不影响我们——工具在发给模型时
就是普通的 tools 数组条目，模型根本不知道背后是个 MCP server。

对照 skill（M9e）：MCP 接入的是**能力**（模型能做的新事情），skill 注入的
是**知识**（怎么做的流程）。

配置文件 `.minicode/mcp.json`：
    {"servers": {"calc": {"command": ["python3", "path/to/server.py"]}}}
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from minicode.tools.base import Tool

PROTOCOL_VERSION = "2025-06-18"


class McpServer:
    """一个 MCP server 连接：子进程 + stdio 上的 JSON-RPC 会话。"""

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self._id = 0
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def _send(self, message: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

        assert self._proc.stdout is not None
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP server {self.name} 意外退出")
            data = json.loads(line)
            if data.get("id") != self._id:
                continue  # 跳过通知和其他消息
            if "error" in data:
                raise RuntimeError(f"MCP 错误：{data['error'].get('message', data['error'])}")
            return data.get("result", {})

    def initialize(self) -> None:
        """MCP 的三步握手：initialize 请求 -> 响应 -> initialized 通知。"""
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "minicode", "version": "0.1.0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list[dict[str, Any]]:
        return self._request("tools/list").get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        text = "\n".join(texts) or "（无文本输出）"
        if result.get("isError"):
            return f"MCP 工具执行出错：{text}"
        return text

    def close(self) -> None:
        self._proc.terminate()


def wrap_as_tools(server: McpServer) -> list[Tool]:
    """把 server 的远程工具包装成本地 Tool 协议。

    命名加 `mcp__<server>__` 前缀防止和本地工具撞名（Claude Code 同款约定）。
    MCP 工具是外部代码，统一按最高警惕的 execute 级别走权限系统。
    """
    tools: list[Tool] = []
    for spec in server.list_tools():
        remote_name = spec["name"]
        tools.append(
            Tool(
                name=f"mcp__{server.name}__{remote_name}",
                description=f"[来自 MCP server {server.name!r}] {spec.get('description', '')}",
                input_schema=spec.get("inputSchema", {"type": "object", "properties": {}}),
                run=lambda tool_input, _n=remote_name: server.call_tool(_n, tool_input),
                permission_level="execute",
            )
        )
    return tools


def load_mcp_tools(cwd: Path | None = None) -> list[Tool]:
    """读 .minicode/mcp.json，启动所有 server，返回全部远程工具。

    在 CLI 入口调用一次，而不是在 Agent 里——避免每个子 agent 都重复
    拉起 server 进程。配置不存在时安静地返回空列表。
    """
    cwd = cwd or Path.cwd()
    config_file = cwd / ".minicode" / "mcp.json"
    if not config_file.is_file():
        return []

    tools: list[Tool] = []
    config = json.loads(config_file.read_text(encoding="utf-8"))
    for name, spec in config.get("servers", {}).items():
        server = McpServer(name, spec["command"])
        server.initialize()
        tools.extend(wrap_as_tools(server))
    return tools
