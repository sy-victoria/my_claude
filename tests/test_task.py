"""task 子 agent 的测试：工具集受限、禁递归、轮数上限、结果回传。"""

from types import SimpleNamespace
import json

from minicode.agent import Agent
from minicode.permissions import PermissionManager
from minicode.tools import task
from minicode.tools.task import build_subagent_tools, task_tool


def test_subagent_tools_are_readonly_and_exclude_task():
    names = {t.name for t in build_subagent_tools()}

    assert names == {"read_file", "list_files", "glob", "grep"}
    assert "task" not in names       # 禁递归
    assert "edit_file" not in names  # 无写权限
    assert "bash" not in names       # 无执行权限


class FakeAPI:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


def _final(text):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def test_task_returns_subagent_final_text(monkeypatch):
    fake_sub = Agent(client=FakeAPI([_final("调查结论：在 permissions.py")]),
                     tools=build_subagent_tools())
    monkeypatch.setattr(task, "subagent_factory", lambda: fake_sub)

    result = task_tool.run({"description": "调查", "prompt": "权限检查在哪里？"})

    assert json.loads(result) == {"status": "complete", "summary": "调查结论：在 permissions.py",
                                  "changed_files": [], "unresolved": []}
    # 子 agent 的中间消息留在它自己的 messages 里
    assert len(fake_sub.messages) == 2


def test_max_loops_stops_runaway_agent():
    tool_use = SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="c", name="list_files", input={})],
    )
    # 模型永远要求调工具，永不给最终答案
    agent = Agent(client=FakeAPI([tool_use] * 10), max_loops=3)

    reply = agent.run_turn("无限循环吧")

    assert "最大循环轮数 3" in reply


def test_tool_budget_preserves_complete_tool_results_and_next_turn():
    calls = []
    class RecordingAPI:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="one", name="unknown", input={}),
                    SimpleNamespace(type="tool_use", id="two", name="unknown", input={}),
                ])
            return _final("已继续")

    agent = Agent(client=RecordingAPI(), max_tool_calls=1)
    assert "提前结束" in agent.run_turn("开始")
    assert agent.last_stop_reason == "tool_limit"
    results = agent.messages[2]["content"]
    assert [item["tool_use_id"] for item in results] == ["one", "two"]
    assert "上限" in results[1]["content"]
    assert agent.run_turn("继续") == "已继续"
    assert len(calls) == 2


def test_turn_deadline_stops_tool_use_without_running_it(monkeypatch):
    clock = [0.0]
    request_timeouts = []
    monkeypatch.setattr("minicode.agent.time.monotonic", lambda: clock[0])

    class SlowAPI:
        def create(self, **kwargs):
            request_timeouts.append(kwargs["timeout"])
            clock[0] = 2.0
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="one", name="unknown", input={})
            ])

    agent = Agent(client=SlowAPI(), max_turn_seconds=1)
    assert "提前结束" in agent.run_turn("开始")
    assert agent.last_stop_reason == "time_limit"
    assert len(agent.messages[2]["content"]) == 1
    assert request_timeouts == [1]


def test_api_failure_after_tool_keeps_recoverable_history():
    class FailingAPI:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="one", name="unknown", input={})
                ])
            if self.calls == 2:
                raise RuntimeError("connection lost")
            return _final("已恢复")

    agent = Agent(client=FailingAPI())
    assert "API 请求失败" in agent.run_turn("开始")
    assert agent.last_stop_reason == "api_error"
    assert [message["role"] for message in agent.messages] == ["user", "assistant", "user", "assistant"]
    assert agent.run_turn("继续") == "已恢复"


def test_api_timeout_at_turn_deadline_reports_incomplete(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("minicode.agent.time.monotonic", lambda: clock[0])

    class TimingOutAPI:
        def create(self, **kwargs):
            assert kwargs["timeout"] == 1
            clock[0] = 1.0
            raise TimeoutError("request expired")

    agent = Agent(client=TimingOutAPI(), max_turn_seconds=1)
    assert "提前结束" in agent.run_turn("任务")
    assert agent.last_stop_reason == "time_limit"
    assert [message["role"] for message in agent.messages] == ["user", "assistant"]


def test_custom_toolset_limits_api_schema():
    captured = []

    class CapturingAPI:
        def create(self, **kwargs):
            captured.append(kwargs)
            return _final("好")

    agent = Agent(client=CapturingAPI(), tools=build_subagent_tools())
    agent.run_turn("你好")

    sent_names = {t["name"] for t in captured[0]["tools"]}
    assert sent_names == {"read_file", "list_files", "glob", "grep"}


def test_work_subagent_inherits_parent_policy_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "subagent_factory", None)
    parent = Agent(api_key="test-key", client=FakeAPI([]), model="chosen-model",
                   base_url="https://example.com", permissions=PermissionManager(
                       cwd=tmp_path, rules={"deny": ["bash:*"]}))
    token = task.current_parent.set(parent)
    try:
        child = task._make_subagent("work")
    finally:
        task.current_parent.reset(token)
    assert child.model == "chosen-model"
    assert child.base_url == "https://example.com"
    assert child.permissions.cwd == tmp_path
    allowed, _ = child.permissions.check(next(t for t in child.tools if t.name == "bash"),
                                          {"command": "echo hi"})
    assert not allowed


def test_work_subagent_inherits_local_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "subagent_factory", None)
    parent = Agent(provider="ollama", model="local-model", client=FakeAPI([]),
                   permissions=PermissionManager(cwd=tmp_path))
    token = task.current_parent.set(parent)
    try:
        child = task._make_subagent("work")
    finally:
        task.current_parent.reset(token)
    assert child.provider == "ollama"
    assert child.model == "local-model"
    assert child.api_key is None
