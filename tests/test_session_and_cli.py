"""M8 测试：会话持久化、slash 命令、Ctrl+C 回滚、消息可序列化。"""

import json
from types import SimpleNamespace

from minicode import session
from minicode.agent import Agent
from minicode.cli import _run_one_turn, handle_slash


class FakeAPI:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        r = self._responses.pop(0)
        # 注意 KeyboardInterrupt 继承自 BaseException 而非 Exception
        if isinstance(r, BaseException):
            raise r
        return r


def _final(text):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


# ---------- 会话持久化 ----------


def test_messages_are_json_serializable_after_turn():
    agent = Agent(client=FakeAPI([_final("你好")]))
    agent.run_turn("hi")

    dumped = json.dumps(agent.messages, ensure_ascii=False)  # 不抛异常即通过

    assert "你好" in dumped


def test_session_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SESSION_DIR", tmp_path)
    agent = Agent(client=FakeAPI([_final("答复")]))
    agent.run_turn("问题")

    path = session.new_session_path()
    session.save(path, agent.messages)
    restored = session.load_latest()

    assert restored == agent.messages


def test_load_latest_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SESSION_DIR", tmp_path / "nothing")

    assert session.load_latest() is None


# ---------- slash 命令 ----------


def _agent():
    return Agent(client=FakeAPI([]))


def test_slash_help_lists_commands():
    out = handle_slash("/help", _agent())

    for cmd in ("/clear", "/compact", "/cost", "/mode", "/model"):
        assert cmd in out


def test_slash_clear_empties_messages():
    agent = Agent(client=FakeAPI([_final("x")]))
    agent.run_turn("hi")

    out = handle_slash("/clear", agent)

    assert agent.messages == []
    assert "清空" in out


def test_slash_mode_switches_permission_mode():
    agent = _agent()

    handle_slash("/mode yolo", agent)

    assert agent.permissions.mode == "yolo"


def test_slash_mode_without_arg_shows_usage():
    out = handle_slash("/mode", _agent())

    assert "用法" in out


def test_slash_model_switches_tier():
    agent = _agent()

    out = handle_slash("/model opus", agent)

    assert agent.model == "deepseek-v4-pro"
    assert "opus" in out


def test_slash_model_uses_explicit_name_for_local_backend():
    agent = Agent(provider="ollama", model="local-a", client=FakeAPI([]))
    assert "local-b" in handle_slash("/model local-b", agent)
    assert agent.model == "local-b"


def test_slash_unknown_command():
    out = handle_slash("/what", _agent())

    assert "未知命令" in out


# ---------- Ctrl+C 回滚 ----------


def test_interrupt_rolls_back_messages():
    """生成途中 Ctrl+C：本轮追加的消息全部丢弃，回到轮次开始前的状态。"""
    agent = Agent(client=FakeAPI([_final("第一轮答复"), KeyboardInterrupt()]))
    agent.run_turn("第一轮")
    before = list(agent.messages)

    _run_one_turn(agent, "会被打断的一轮")

    assert agent.messages == before
