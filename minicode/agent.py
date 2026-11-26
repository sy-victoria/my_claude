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

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

import anthropic

from minicode.config import BASE_URL, MAX_TOKENS, resolve_model
from minicode.context import SUMMARY_INSTRUCTION, ContextTracker, merge_summary, split_for_compaction
from minicode.hooks import load_hooks, run_hooks
from minicode.permissions import PermissionManager
from minicode.prompts import build_system_prompt
from minicode.sandbox import sandbox_argv, stop_sandbox, uses_docker
from minicode.tools import TOOLS
from minicode.tools.base import Tool

# 工具调用时的回调：(工具名, 工具输入) -> None，CLI 用它打印调用日志。
ToolCallHook = Callable[[str, dict[str, Any]], None]
# 流式文本回调：每收到一段文本增量调用一次，CLI 用它边生成边渲染。
TextHook = Callable[[str], None]


def _block_to_dict(block: Any) -> dict[str, Any]:
    """把 SDK 返回的内容块转成普通 dict 再存进 messages。

    两个目的：一是 messages 全程保持 JSON 可序列化（M8 的会话持久化直接
    json.dump 即可）；二是消除对 SDK 对象类型的依赖（测试里的假响应用
    SimpleNamespace 也能走同一条路径）。API 完全接受 dict 形式的内容块。
    """
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(vars(block))


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
        tools: list[Tool] | None = None,
        max_loops: int | None = 40,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        if client is not None:
            self._messages_api = client
        else:
            if not api_key:
                raise ValueError("必须提供 api_key（或直接传入 client 用于测试）")
            real_client = anthropic.Anthropic(api_key=api_key, base_url=base_url or BASE_URL)
            self._messages_api = real_client.messages

        self.api_key = api_key
        self.base_url = base_url or BASE_URL

        self.tier = tier  # 当前档位标签（"sonnet"/"opus"），供终端显示用
        self.model = model or resolve_model(tier)
        self.messages: list[dict[str, Any]] = []
        self.on_tool_call = on_tool_call
        # 工具执行完之后的回调（name, tool_input, result_text），无论成功/
        # 拒绝/报错都会触发。带上 tool_input 是为了让终端能在 edit_file 时
        # 用 old_str/new_str 画彩色 diff，而不用重新读一遍文件。不是构造
        # 参数——跟 on_compact 一样，属于"终端要不要展示"这层可选装饰，
        # 由调用方（cli.py）事后挂上去，不污染 Agent 的必需依赖。
        self.on_tool_result: Callable[[str, dict[str, Any], str], None] | None = None
        self.permissions = permissions or PermissionManager(mode="default")
        # 工具集可定制：主 agent 用全量 TOOLS；子 agent（M7 task 工具派生）
        # 只拿到只读子集，且不含 task 自身——防止递归派生。
        self.tools = tools if tools is not None else TOOLS
        self._tools_by_name = {t.name: t for t in self.tools}
        # 单轮对话内的最大循环次数（子 agent 用，防失控）；None = 不限制。
        self.max_loops = max_loops
        self.plan_mode = False
        self._full_tools = self.tools  # plan mode 退出时恢复用
        # 用户配置的工具前后钩子（M9c），启动时加载一次
        self.hooks = load_hooks(self.permissions.cwd)
        # system prompt 在会话开始时组装一次（含 cwd/日期/项目记忆），之后
        # 每次请求都通过 system 参数携带——它不进 messages，所以永远不会
        # 被当成对话历史，也不会被未来的 compaction（M6）压缩掉。
        self.system_prompt = build_system_prompt(self.permissions.cwd)
        # 已读文件集合：edit_file 修改已存在的文件前，必须先 read_file 过它
        # （M1 验收时发现模型"自发"先读，但不能依赖模型的好习惯——这是
        # Claude Code 的真实硬约束，防止模型凭想象改文件）。
        self._read_files: set[Path] = set()
        self.context = ContextTracker()
        self.last_stop_reason: str | None = None
        # compaction 发生时的通知回调（CLI 用它提示用户），(压缩前消息数, 压缩后消息数)
        self.on_compact: Callable[[int, int], None] | None = None

    def run_turn(self, user_input: str, on_text: TextHook | None = None) -> str:
        """处理一轮用户输入，驱动循环直到模型给出最终文本回复。

        返回模型最后一次回复里的纯文本，供 CLI 打印。中间发生的所有工具
        调用都会被记录进 self.messages，调用方不需要关心循环了几轮。
        传入 on_text 时启用流式输出：文本增量一边生成一边回调（仅真实
        SDK client 支持；测试用的假 client 没有 stream 方法，自动回退）。
        """
        # 在轮次边界检查是否需要压缩：此刻 messages 一定以完整的
        # assistant 回复结尾，不会把进行到一半的工具调用链压断。
        self.last_stop_reason = None
        if self.context.should_compact():
            self.compact()

        turn_start = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})

        loops = 0
        while True:
            loops += 1
            if self.max_loops is not None and loops > self.max_loops:
                self.last_stop_reason = "loop_limit"
                message = f"[已达到最大循环轮数 {self.max_loops}，任务提前结束]"
                self.messages.append({"role": "assistant", "content": [{"type": "text", "text": message}]})
                return message
            try:
                response = self._request(on_text)
            except Exception:
                # API 失败时撤销本轮消息，保证会话可继续；工具副作用无法撤销。
                del self.messages[turn_start:]
                raise
            self.context.record(response)
            self.messages.append(
                {"role": "assistant", "content": [_block_to_dict(b) for b in response.content]}
            )

            if response.stop_reason != "tool_use":
                self.last_stop_reason = response.stop_reason
                return self._extract_text(response.content)

            tool_results = [
                self._run_tool_use_block(block)
                for block in response.content
                if block.type == "tool_use"
            ]
            self.messages.append({"role": "user", "content": tool_results})

    def _request(self, on_text: TextHook | None) -> Any:
        """发一次 API 请求。有 on_text 且 client 支持时走流式接口。"""
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system_prompt,
            tools=[tool.to_api_schema() for tool in self.tools],
            messages=self.messages,
        )
        if on_text is not None and hasattr(self._messages_api, "stream"):
            with self._messages_api.stream(**kwargs) as stream:
                for chunk in stream.text_stream:
                    on_text(chunk)
                return stream.get_final_message()
        return self._messages_api.create(**kwargs)

    # plan mode 追加到 system prompt 的指令（M9b）。用类常量方便退出时精确移除。
    PLAN_MODE_PROMPT = (
        "\n\n[计划模式] 当前处于 plan mode：只允许调研和阅读，禁止任何修改。"
        "请充分调研后给出实施方案（要改哪些文件、怎么改、有什么风险），"
        "等待用户批准后再动手。"
    )

    def set_plan_mode(self, enabled: bool) -> None:
        """切换 plan mode（M9b，复现 Claude Code 的 plan mode）。

        双保险：工具集物理切到只读子集（结构保证，模型想改也没有写工具
        可调），同时 system prompt 追加只读指令（行为引导，让它主动输出
        方案而不是反复撞墙）。复用了 M7 引入的自定义工具集机制。
        """
        if enabled == self.plan_mode:
            return
        self.plan_mode = enabled
        if enabled:
            self._full_tools = self.tools
            self.tools = [t for t in self.tools if t.permission_level == "read"]
            self.system_prompt += self.PLAN_MODE_PROMPT
        else:
            self.tools = self._full_tools
            self.system_prompt = self.system_prompt.replace(self.PLAN_MODE_PROMPT, "")
        self._tools_by_name = {t.name: t for t in self.tools}

    def compact(self) -> bool:
        """把旧对话历史压缩成摘要。返回是否真的发生了压缩。

        本质是"用一次 API 调用买回上下文空间"：让模型总结旧历史，用几百
        token 的摘要替换掉可能几万 token 的原文。摘要并入保留部分的第一条
        用户消息，维持角色交替的合法结构。
        """
        older, recent = split_for_compaction(self.messages)
        if not older:
            return False  # 只有当前一轮对话，没有可压缩的旧历史

        response = self._messages_api.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system="你是一个对话总结助手。",
            messages=[*older, {"role": "user", "content": SUMMARY_INSTRUCTION}],
        )
        summary = self._extract_text(response.content)

        before = len(self.messages)
        self.messages = merge_summary(summary, recent)
        # 压缩后旧的 token 计数已失真，归零等下一次响应刷新。
        self.context.last_input_tokens = 0
        if self.on_compact:
            self.on_compact(before, len(self.messages))
        return True

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

        result_text = self._run_tool(name, tool_input)

        if self.on_tool_result:
            self.on_tool_result(name, tool_input, result_text)
        return result_text

    def _run_tool(self, name: str, tool_input: dict[str, Any]) -> str:
        """真正跑一次工具调用，返回结果文本（成功/拒绝/报错都在这里产生）。

        单独拆出来是为了让 _execute_tool 只有一个返回结果的出口——这样
        on_tool_result 回调无论走到哪条分支都只需要挂一次，不用在每个
        return 前都补一句。
        """
        tool = self._tools_by_name.get(name)
        if tool is None:
            return f"错误：未知工具 {name}"
        if self.plan_mode and name == "task" and tool_input.get("mode") == "work":
            return "错误：计划模式不允许可写子 agent"

        # 读后编辑约束：这条策略需要跨工具的会话状态（谁被读过），所以放在
        # agent 层而不是工具内部。放在权限检查之前——注定失败的调用没必要
        # 再去打扰用户确认。
        if name == "edit_file" and tool_input.get("old_str"):
            target = (self.permissions.cwd / tool_input.get("path", "")).resolve()
            if target.exists() and target not in self._read_files:
                return (
                    f"错误：编辑前必须先读取文件。请先用 read_file 读取 "
                    f"{tool_input.get('path')} 的当前内容，再进行编辑。"
                )

        # 所有工具执行前统一过权限守门人——工具自己不做权限判断。
        allowed, deny_reason = self.permissions.check(tool, tool_input)
        if not allowed:
            return deny_reason

        # pre_tool hook（M9c）：用户配置的前置校验，非零退出阻止执行。
        hook_ok, hook_reason = run_hooks(self.hooks, "pre_tool", name, tool_input,
                                         cwd=self.permissions.cwd)
        if not hook_ok:
            return f"操作被 pre_tool hook 阻止：{hook_reason}"

        try:
            if name == "task":
                from minicode.tools.task import current_parent
                token = current_parent.set(self)
                try:
                    result = tool.run(tool_input)
                finally:
                    current_parent.reset(token)
            elif name in {"read_file", "list_files", "glob", "grep", "edit_file", "write_file"}:
                result = self._run_file_tool(name, tool_input)
            else:
                result = tool.run(tool_input)
            if name == "read_file" and not result.startswith("错误"):
                self._read_files.add((self.permissions.cwd / tool_input.get("path", "")).resolve())
            run_hooks(self.hooks, "post_tool", name, tool_input, cwd=self.permissions.cwd)
            return result
        except Exception as exc:
            # 工具报错不能让整个 agent 崩溃：把错误信息当成一条 tool_result
            # 返回给模型，模型看得懂错误、通常会自己调整下一步操作。
            return f"工具执行出错：{exc}"

    def _run_file_tool(self, name: str, tool_input: dict[str, Any]) -> str:
        """文件操作通过隔离进程执行；Windows 路径映射到容器工作区。"""
        worker_input = dict(tool_input)
        if uses_docker():
            path = (self.permissions.cwd / worker_input.get("path", ".")).resolve()
            relative = path.relative_to(self.permissions.cwd)
            worker_input["path"] = "/workspace" + ("/" + relative.as_posix() if relative.parts else "")
        argv, env = sandbox_argv([sys.executable, "-m", "minicode.tool_worker"], self.permissions.cwd)
        try:
            worker = subprocess.run(argv, input=json.dumps({"name": name, "input": worker_input}),
                                    text=True, encoding="utf-8", capture_output=True, timeout=30, env=env)
        except subprocess.TimeoutExpired:
            stop_sandbox(argv, env)
            raise
        if worker.returncode:
            raise RuntimeError(worker.stderr.strip() or worker.stdout.strip())
        result: str = json.loads(worker.stdout)["result"]
        if uses_docker() and name in {"glob", "grep", "edit_file", "write_file"}:
            result = result.replace("/workspace/", self.permissions.cwd.as_posix() + "/")
        return result

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        return "".join(block.text for block in content if block.type == "text")
