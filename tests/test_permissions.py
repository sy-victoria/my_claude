"""权限系统测试：决策矩阵、会话白名单、y/a/n 三种用户答复，以及
agent 循环与权限层的集成（拒绝理由要作为 tool_result 喂回模型）。
"""

from types import SimpleNamespace

import pytest

from minicode.agent import Agent
from minicode.permissions import PermissionManager, decide
from minicode.tools import get_tool

# ---------- 决策矩阵（纯函数，无交互） ----------

# (mode, level) -> 预期决策。这是 roadmap M3 要求的 3×3 矩阵的完整枚举。
MATRIX = [
    ("default", "read", "allow"),
    ("default", "write", "ask"),
    ("default", "execute", "ask"),
    ("accept-edits", "read", "allow"),
    ("accept-edits", "write", "allow"),
    ("accept-edits", "execute", "ask"),
    ("yolo", "read", "allow"),
    ("yolo", "write", "allow"),
    ("yolo", "execute", "allow"),
]


@pytest.mark.parametrize("mode,level,expected", MATRIX)
def test_decision_matrix(mode, level, expected):
    assert decide(mode, level, in_allowlist=False) == expected


def test_allowlist_overrides_ask():
    assert decide("default", "execute", in_allowlist=True) == "allow"


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        PermissionManager(mode="whatever")


# ---------- check()：y / a / n 三种答复 ----------


def _manager(mode, answers: list[str]) -> tuple[PermissionManager, list[str]]:
    """构造一个用预设答案回答询问的 manager，并记录每次被询问的工具名。"""
    asked: list[str] = []

    def fake_ask(tool_name, tool_input):
        asked.append(tool_name)
        return answers.pop(0)

    return PermissionManager(mode=mode, ask_user=fake_ask), asked


def test_read_tool_does_not_ask_in_default_mode():
    manager, asked = _manager("default", [])

    allowed, reason = manager.check(get_tool("read_file"), {"path": "x"})

    assert allowed
    assert asked == []


def test_answer_y_allows_once_but_asks_again():
    manager, asked = _manager("default", ["y", "y"])
    bash = get_tool("bash")

    assert manager.check(bash, {"command": "ls"}) == (True, "")
    assert manager.check(bash, {"command": "ls"}) == (True, "")
    # y 只是本次允许，第二次调用仍然要询问。
    assert asked == ["bash", "bash"]


def test_answer_a_adds_to_session_allowlist():
    manager, asked = _manager("default", ["a"])
    bash = get_tool("bash")

    assert manager.check(bash, {"command": "ls"}) == (True, "")
    allowed, _ = manager.check(bash, {"command": "pwd"})

    assert allowed
    # a 之后同一会话内不再询问。
    assert asked == ["bash"]


def test_answer_n_denies_with_reason_for_model():
    manager, _ = _manager("default", ["n"])

    allowed, reason = manager.check(get_tool("bash"), {"command": "ls"})

    assert not allowed
    assert "拒绝" in reason


# ---------- 与 agent 循环的集成 ----------


class FakeMessagesAPI:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)

    def create(self, **kwargs) -> SimpleNamespace:
        return self._responses.pop(0)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use(name, tool_input):
    return SimpleNamespace(type="tool_use", id="call_1", name=name, input=tool_input)


def test_denied_tool_result_reaches_model(tmp_path):
    """用户拒绝时：工具不执行，拒绝理由作为 tool_result 进入 messages。"""
    target = tmp_path / "a.txt"
    target.write_text("原内容")

    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[_tool_use("edit_file", {"path": str(target), "old_str": "原内容", "new_str": "新内容"})],
        ),
        SimpleNamespace(stop_reason="end_turn", content=[_text("好的，我不改了。")]),
    ]
    manager = PermissionManager(mode="default", ask_user=lambda name, inp: "n")
    agent = Agent(client=FakeMessagesAPI(responses), permissions=manager)
    # 本测试只关心权限拒绝，预置"已读"状态绕过 M5 的读后编辑约束。
    agent._read_files.add(target.resolve())

    reply = agent.run_turn("把 a.txt 改掉")

    assert reply == "好的，我不改了。"
    assert "拒绝" in agent.messages[2]["content"][0]["content"]
    # 文件必须原封不动——拒绝意味着工具根本没执行。
    assert target.read_text() == "原内容"


def test_yolo_mode_executes_write_without_asking(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("原内容")

    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[_tool_use("edit_file", {"path": str(target), "old_str": "原内容", "new_str": "新内容"})],
        ),
        SimpleNamespace(stop_reason="end_turn", content=[_text("改好了")]),
    ]
    asked = []
    manager = PermissionManager(mode="yolo", ask_user=lambda name, inp: asked.append(name) or "n")
    agent = Agent(client=FakeMessagesAPI(responses), permissions=manager)
    agent._read_files.add(target.resolve())

    agent.run_turn("把 a.txt 改掉")

    assert target.read_text() == "新内容"
    assert asked == []
