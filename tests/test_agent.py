"""agent 核心循环的测试：不调真实 API（省钱），用一个手写的假 client
模拟「模型要求调用工具」和「模型给出最终回复」两种响应。

假 client 只需要实现 Agent 用到的那一小块接口：一个 create(**kwargs) 方法，
按调用顺序依次返回预先准备好的响应——这就是 CLAUDE.md 里说的"依赖注入"，
用一个构造函数参数替换掉真实网络请求，不需要 mock 框架。
"""

from types import SimpleNamespace
import os
import sys

from minicode.agent import Agent
from minicode.permissions import PermissionManager


class FakeMessagesAPI:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(block_id: str, name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def test_run_turn_executes_tool_then_returns_final_text(tmp_path):
    first_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[_tool_use_block("call_1", "list_files", {"path": str(tmp_path)})],
    )
    second_response = SimpleNamespace(
        stop_reason="end_turn",
        content=[_text_block("目录是空的。")],
    )
    fake_client = FakeMessagesAPI([first_response, second_response])
    agent = Agent(client=fake_client)

    reply = agent.run_turn("这个目录里有什么文件？")

    assert reply == "目录是空的。"
    assert len(fake_client.calls) == 2
    # messages 应该依次是：用户输入、模型的 tool_use、工具结果、模型的最终文本。
    roles = [m["role"] for m in agent.messages]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_run_turn_with_no_tool_use_returns_immediately():
    response = SimpleNamespace(stop_reason="end_turn", content=[_text_block("你好！")])
    fake_client = FakeMessagesAPI([response])
    agent = Agent(client=fake_client)

    reply = agent.run_turn("你好")

    assert reply == "你好！"
    assert len(fake_client.calls) == 1


def test_tool_error_is_fed_back_to_model_not_raised():
    tool_use_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[_tool_use_block("call_1", "read_file", {"path": "不存在的文件.txt"})],
    )
    final_response = SimpleNamespace(
        stop_reason="end_turn", content=[_text_block("好的，文件不存在。")]
    )
    fake_client = FakeMessagesAPI([tool_use_response, final_response])
    agent = Agent(client=fake_client)

    reply = agent.run_turn("读一下这个文件")

    assert reply == "好的，文件不存在。"
    tool_result_message = agent.messages[2]
    assert "错误" in tool_result_message["content"][0]["content"]


def test_unknown_tool_name_returns_error_without_crashing():
    tool_use_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[_tool_use_block("call_1", "does_not_exist", {})],
    )
    final_response = SimpleNamespace(stop_reason="end_turn", content=[_text_block("明白")])
    fake_client = FakeMessagesAPI([tool_use_response, final_response])
    agent = Agent(client=fake_client)

    reply = agent.run_turn("随便做点什么")

    assert reply == "明白"
    tool_result_message = agent.messages[2]
    assert "未知工具" in tool_result_message["content"][0]["content"]


def test_on_tool_call_hook_receives_name_and_input(tmp_path):
    tool_use_response = SimpleNamespace(
        stop_reason="tool_use",
        content=[_tool_use_block("call_1", "list_files", {"path": str(tmp_path)})],
    )
    final_response = SimpleNamespace(stop_reason="end_turn", content=[_text_block("完成")])
    fake_client = FakeMessagesAPI([tool_use_response, final_response])

    seen: list[tuple[str, dict]] = []
    agent = Agent(client=fake_client, on_tool_call=lambda name, inp: seen.append((name, inp)))

    agent.run_turn("列出文件")

    assert seen == [("list_files", {"path": str(tmp_path)})]


def test_bash_uses_agent_workspace_not_process_directory(tmp_path, monkeypatch):
    seen = []
    def fake_sandbox(command, cwd=None):
        seen.append((command, cwd))
        return [sys.executable, "-c", "print('ok')"], os.environ.copy()

    monkeypatch.setattr("minicode.tools.bash.sandbox_command", fake_sandbox)
    agent = Agent(client=FakeMessagesAPI([]), permissions=PermissionManager(mode="yolo", cwd=tmp_path))
    assert "ok" in agent._run_tool("bash", {"command": "echo ok"})
    assert seen == [("echo ok", tmp_path)]
