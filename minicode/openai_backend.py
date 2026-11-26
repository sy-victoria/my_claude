"""将 OpenAI Chat Completions 兼容端点适配为现有 agent 的消息接口。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Any


OPENAI_BASE_URL = "https://api.openai.com/v1"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: urllib.request.Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        raise PermissionError("模型端点不允许重定向认证请求")


def _validate_base_url(url: str, api_key: str | None) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("模型端点 URL 不得包含凭据、查询参数或片段")
    if parsed.scheme == "https" and parsed.hostname:
        return url.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"} and not api_key:
        return url.rstrip("/")
    raise ValueError("模型端点必须使用 HTTPS；无密钥的本机端点可使用 HTTP")


def _to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """会话仍以 Anthropic 内容块存储，只在网络边界转换格式。"""
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for item in messages:
        content = item["content"]
        if item["role"] == "user" and isinstance(content, str):
            converted.append({"role": "user", "content": content})
        elif item["role"] == "assistant" and isinstance(content, list):
            text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
            calls = [{"id": block["id"], "type": "function", "function": {
                "name": block["name"], "arguments": json.dumps(block["input"], ensure_ascii=False)}}
                     for block in content if block.get("type") == "tool_use"]
            reply: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                reply["tool_calls"] = calls
            converted.append(reply)
        elif item["role"] == "user" and isinstance(content, list):
            for block in content:
                if block.get("type") != "tool_result":
                    raise ValueError("不支持的工具结果内容块")
                converted.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                                  "content": str(block.get("content", ""))})
        else:
            raise ValueError("不支持的会话消息格式")
    return converted


class OpenAIChatAdapter:
    """保持 Agent 的 create() 边界，允许 OpenAI 与本地 Ollama 使用同一工具循环。"""

    def __init__(self, base_url: str, api_key: str | None, timeout: float = 90) -> None:
        self.base_url = _validate_base_url(base_url, api_key)
        self.api_key = api_key
        self.timeout = timeout

    def create(self, **kwargs: Any) -> Any:
        tools = [{"type": "function", "function": {
            "name": spec["name"], "description": spec.get("description", ""),
            "parameters": spec["input_schema"]}} for spec in kwargs.get("tools", [])]
        payload = {"model": kwargs["model"], "max_tokens": kwargs["max_tokens"],
                   "messages": _to_openai_messages(kwargs["system"], kwargs["messages"])}
        if tools:
            payload["tools"] = tools
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.base_url + "/chat/completions",
                                         json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                body = response.read(10_000_001)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"模型端点 HTTP {exc.code}") from exc
        if len(body) > 10_000_000:
            raise ValueError("模型响应超过 10 MB")
        data = json.loads(body)
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("模型响应缺少 choices")
        choice = choices[0]
        message = choice["message"]
        blocks: list[Any] = []
        if message.get("content"):
            blocks.append(SimpleNamespace(type="text", text=message["content"]))
        for call in message.get("tool_calls") or []:
            arguments = json.loads(call["function"]["arguments"] or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("模型工具参数必须是 JSON 对象")
            blocks.append(SimpleNamespace(type="tool_use", id=call["id"],
                                          name=call["function"]["name"], input=arguments))
        reason = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens",
                  "content_filter": "content_filter"}.get(choice.get("finish_reason"), choice.get("finish_reason"))
        usage = data.get("usage") or {}
        usage_obj = SimpleNamespace(input_tokens=usage.get("prompt_tokens", 0),
                                    output_tokens=usage.get("completion_tokens", 0))
        return SimpleNamespace(stop_reason=reason, content=blocks, usage=usage_obj)
