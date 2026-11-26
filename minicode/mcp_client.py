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
import atexit
import os
import queue
import subprocess
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from minicode.tools.base import Tool
from minicode.sandbox import sandbox_argv, stop_sandbox

PROTOCOL_VERSION = "2025-06-18"
REQUEST_TIMEOUT_SECONDS = 15


class McpSessionExpired(RuntimeError):
    """服务端已终止当前 HTTP 会话；调用方需重新握手。"""


class McpServer:
    """一个 MCP server 连接：子进程 + stdio 上的 JSON-RPC 会话。"""

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self._id = 0
        argv, env = sandbox_argv(command, writable_workspace=False)
        self._sandbox_argv = argv
        self._sandbox_env = env
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
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
        incoming: queue.Queue[str | BaseException] = queue.Queue(maxsize=1)
        def read_reply() -> None:
            try:
                while True:
                    line = self._proc.stdout.readline()  # type: ignore[union-attr]
                    if not line:
                        raise RuntimeError(f"MCP server {self.name} 意外退出")
                    data = json.loads(line)
                    if data.get("id") == self._id:
                        incoming.put(line)
                        return
            except BaseException as exc:
                incoming.put(exc)
        threading.Thread(target=read_reply, daemon=True).start()
        try:
            item = incoming.get(timeout=REQUEST_TIMEOUT_SECONDS)
        except queue.Empty:
            self.close()
            raise TimeoutError(f"MCP server {self.name} 请求 {method} 超时") from None
        if isinstance(item, BaseException):
            raise item
        data = json.loads(item)
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
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        stop_sandbox(self._sandbox_argv, self._sandbox_env)


class HttpMcpServer:
    """最小 Streamable HTTP MCP 客户端，支持 JSON 与 SSE 响应。"""

    def __init__(self, name: str, url: str, token_env: str | None = None) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("远程 MCP 必须使用 HTTPS（本机可使用 HTTP）")
        self.name = name
        self.url = url
        self.token_env = token_env
        self.session_id: str | None = None
        self._id = 0

    def _send(self, method: str, params: dict[str, Any] | None = None, notify: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            self._id += 1
            body["id"] = self._id
        if params is not None:
            body["params"] = params
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.token_env:
            token = os.environ.get(self.token_env)
            if not token:
                raise ValueError(f"缺少 MCP 认证环境变量 {self.token_env}")
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.url, json.dumps(body).encode(), headers=headers, method="POST")
        try:
            response = urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and self.session_id:
                self.session_id = None
                raise McpSessionExpired(f"MCP server {self.name} 会话已过期") from exc
            if exc.code == 401:
                raise PermissionError(f"MCP server {self.name} 认证失败；请检查 token_env") from exc
            raise
        with response:
            self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
            if notify:
                return {}
            if response.headers.get_content_type() == "text/event-stream":
                event_data: list[str] = []
                total = 0
                while line := response.readline():
                    total += len(line)
                    if total > 2_000_000:
                        raise ValueError("MCP 响应超过 2 MB")
                    decoded = line.decode().strip()
                    if decoded.startswith("data:"):
                        event_data.append(decoded[5:].strip())
                    elif not decoded and event_data:
                        candidate = json.loads("\n".join(event_data))
                        if candidate.get("id") == self._id:
                            payload = candidate
                            break
                        event_data.clear()
                else:
                    raise ValueError("MCP SSE 响应缺少匹配的结果事件")
            else:
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise ValueError("MCP 响应超过 2 MB")
                payload = json.loads(content)
            if "error" in payload:
                raise RuntimeError(f"MCP 错误：{payload['error']}")
            return payload.get("result", {})

    def initialize(self) -> None:
        self._send("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                  "clientInfo": {"name": "minicode", "version": "0.1.0"}})
        self._send("notifications/initialized", notify=True)

    def list_tools(self) -> list[dict[str, Any]]:
        try:
            return self._send("tools/list").get("tools", [])
        except (OSError, ValueError, McpSessionExpired):
            # 发现工具是只读操作，连接中断后可以安全地重新握手并重试一次。
            self.session_id = None
            self.initialize()
            return self._send("tools/list").get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        try:
            result = self._send("tools/call", {"name": tool_name, "arguments": arguments})
        except McpSessionExpired:
            # 工具可能已有副作用，不自动重放；恢复连接供后续请求使用。
            self.initialize()
            return "MCP 会话已过期，连接已恢复；本次工具调用结果未知，请先检查状态再决定是否重试"
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        return f"MCP 工具执行出错：{text}" if result.get("isError") else text or "（无文本输出）"

    def close(self) -> None:
        if self.session_id:
            request = urllib.request.Request(self.url, headers={"Mcp-Session-Id": self.session_id}, method="DELETE")
            try:
                urllib.request.urlopen(request, timeout=2).close()
            except Exception:
                pass


def wrap_as_tools(server: McpServer | HttpMcpServer) -> list[Tool]:
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
    tools: list[Tool] = []
    configs = [(cwd / ".minicode" / "mcp.json", False),
               (Path.home() / ".minicode" / "mcp.json", True)]
    servers: dict[str, tuple[dict[str, Any], bool]] = {}
    for config_file, is_user in configs:
        if not config_file.is_file():
            continue
        config = json.loads(config_file.read_text(encoding="utf-8"))
        for name, spec in config.get("servers", {}).items():
            if "url" in spec and not is_user:
                raise ValueError("远程 MCP 必须配置在用户级 ~/.minicode/mcp.json，不能从项目配置自动连接")
            servers[name] = (spec, is_user)
    for name, (spec, _is_user) in servers.items():
        server = (HttpMcpServer(name, spec["url"], spec.get("token_env")) if "url" in spec
                  else McpServer(name, spec["command"]))
        atexit.register(server.close)
        server.initialize()
        tools.extend(wrap_as_tools(server))
    return tools
