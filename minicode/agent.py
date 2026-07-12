"""核心 agent 循环 —— 全项目最重要的文件。

agent 的本质是「LLM + 工具 + 循环」（详见 docs/01-architecture.md 第 1 节），
唯一的状态是 `self.messages` 列表，没有状态机、没有工作流图：

    messages.append(用户输入)
    loop:
        response = client.messages.create(model, messages, tools=...)
        messages.append(response 的 assistant 内容块)
        if response.stop_reason != "tool_use":
            return  # 模型说完了，把话筒还给用户
        for 每个 tool_use 块:
            result = 执行对应工具（异常要捕获，错误文本也返回给模型）
            messages.append(role=user 的 tool_result 块)
        # 继续 loop，把工具结果喂回模型

模型从不「执行」任何东西——它只输出「我想调用 xxx，参数是 ...」这样的结构化
意图，真正执行的是下面 `_execute_tool` 里的本地 Python 代码。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

import anthropic

from minicode.config import BASE_URL, MAX_TOKENS, resolve_model
from minicode.permissions import PermissionManager
from minicode.tools import TOOLS, get_tool

# 工具调用时的回调：(工具名, 工具输入) -> None，CLI 用它打印调用日志。
ToolCallHook = Callable[[str, dict[str, Any]], None]


class _MessagesClient(Protocol):
    """Anthropic SDK 里我们实际用到的那一小块接口。

    只声明用到的方法，是为了让测试可以传入一个不依赖真实网络请求的假
    client（见 tests/test_agent.py），同时不引入额外的抽象层——这仍然是
    "直白"的依赖注入，不是完整的 Provider 框架。
    """

    def create(self, **kwargs: Any) -> Any: ...


class Agent:
    def __init__(
        self,
        api_key: str | None = None,
        tier: str = "sonnet",
        client: _MessagesClient | None = None,
        on_tool_call: ToolCallHook | None = None,
        permissions: PermissionManager | None = None,
    ) -> None:
        if client is not None:
            self._messages_api = client
        else:
            if not api_key:
                raise ValueError("必须提供 api_key（或直接传入 client 用于测试）")
            real_client = anthropic.Anthropic(api_key=api_key, base_url=BASE_URL)
            self._messages_api = real_client.messages

        self.model = resolve_model(tier)
        self.messages: list[dict[str, Any]] = []
        self.on_tool_call = on_tool_call
        self.permissions = permissions or PermissionManager(mode="default")

    def run_turn(self, user_input: str) -> str:
        """处理一轮用户输入，驱动循环直到模型给出最终文本回复。

        返回模型最后一次回复里的纯文本，供 CLI 打印。中间发生的所有工具
        调用都会被记录进 self.messages，调用方不需要关心循环了几轮。
        """
        self.messages.append({"role": "user", "content": user_input})

        while True:
            response = self._messages_api.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                tools=[tool.to_api_schema() for tool in TOOLS],
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return self._extract_text(response.content)

            tool_results = [
                self._run_tool_use_block(block)
                for block in response.content
                if block.type == "tool_use"
            ]
            self.messages.append({"role": "user", "content": tool_results})

    def _run_tool_use_block(self, block: Any) -> dict[str, Any]:
        result_text = self._execute_tool(block.name, block.input)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result_text,
        }

    def _execute_tool(self, name: str, tool_input: dict[str, Any]) -> str:
        if self.on_tool_call:
            self.on_tool_call(name, tool_input)

        tool = get_tool(name)
        if tool is None:
            return f"错误：未知工具 {name}"

        # 所有工具执行前统一过权限守门人——工具自己不做权限判断。
        allowed, deny_reason = self.permissions.check(tool, tool_input)
        if not allowed:
            return deny_reason

        try:
            return tool.run(tool_input)
        except Exception as exc:
            # 工具报错不能让整个 agent 崩溃：把错误信息当成一条 tool_result
            # 返回给模型，模型看得懂错误、通常会自己调整下一步操作。
            return f"工具执行出错：{exc}"

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        return "".join(block.text for block in content if block.type == "text")
