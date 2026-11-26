"""M9a/M9f/M9c 测试：todo 工具、goal 模式循环、hooks 机制。"""

import json
import os
from types import SimpleNamespace

import pytest

from minicode import hooks as hooks_mod
from minicode.agent import Agent
from minicode.cli import run_goal_mode
from minicode.permissions import PermissionManager
from minicode.tools import todo
from minicode.tools.todo import todo_tool

# ---------- M9a: todo ----------


def test_todo_updates_state_and_renders(monkeypatch):
    shown = []
    monkeypatch.setattr(todo, "on_todo_update", lambda r: shown.append(r))

    result = todo_tool.run({"todos": [
        {"content": "写代码", "status": "completed"},
        {"content": "跑测试", "status": "in_progress"},
        {"content": "写文档", "status": "pending"},
    ]})

    assert todo.current_todos[1]["content"] == "跑测试"
    assert "☑ 写代码" in result and "◐ 跑测试" in result and "☐ 写文档" in result
    assert len(shown) == 1


def test_todo_rejects_invalid_status():
    result = todo_tool.run({"todos": [{"content": "x", "status": "done"}]})

    assert "错误" in result


# ---------- M9f: goal 模式 ----------


class FakeAPI:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


def _final(text):
    return SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
    )


def test_goal_mode_loops_until_done():
    agent = Agent(client=FakeAPI([_final("做了一半"), _final("全部完成 <DONE>")]))

    finished = run_goal_mode(agent, "测试目标", max_rounds=5)

    assert finished
    assert len(agent.messages) == 4  # 两轮：目标+回复、继续+回复


def test_goal_mode_respects_round_limit():
    agent = Agent(client=FakeAPI([_final("还在做")] * 3))

    finished = run_goal_mode(agent, "永远做不完", max_rounds=3)

    assert not finished


# ---------- M9c: hooks ----------


def _agent_with_hooks(tmp_path, hooks_config, responses):
    (tmp_path / ".minicode").mkdir(exist_ok=True)
    (tmp_path / ".minicode" / "hooks.json").write_text(json.dumps(hooks_config))
    agent = Agent(client=FakeAPI(responses), permissions=PermissionManager(mode="yolo", cwd=tmp_path))
    agent.hooks = hooks_mod.load_hooks(tmp_path)
    return agent


def _tool_use(name, tool_input):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="c", name=name, input=tool_input)],
    )


@pytest.mark.skipif(os.name != "posix", reason="hooks require Linux sandbox")
def test_pre_hook_nonzero_exit_blocks_tool(tmp_path):
    target = tmp_path / "a.txt"
    responses = [
        _tool_use("write_file", {"path": str(target), "content": "x"}),
        _final("好吧"),
    ]
    agent = _agent_with_hooks(
        tmp_path,
        {"pre_tool": [{"tool": "write_file", "command": "echo 禁止写入 >&2; exit 1"}]},
        responses,
    )

    agent.run_turn("写个文件")

    assert not target.exists()  # 工具被 hook 阻止，未执行
    assert "禁止写入" in agent.messages[2]["content"][0]["content"]


@pytest.mark.skipif(os.name != "posix", reason="hooks require Linux sandbox")
def test_post_hook_runs_with_env_vars(tmp_path):
    target = tmp_path / "a.txt"
    marker = tmp_path / "hook_ran.txt"
    responses = [
        _tool_use("write_file", {"path": str(target), "content": "x"}),
        _final("完成"),
    ]
    agent = _agent_with_hooks(
        tmp_path,
        {"post_tool": [{"tool": "write_file", "command": f'echo "$TOOL_NAME $TOOL_FILE" > {marker}'}]},
        responses,
    )

    agent.run_turn("写个文件")

    assert target.exists()
    assert "write_file" in marker.read_text()
    assert str(target) in marker.read_text()


def test_hook_without_tool_filter_matches_all(tmp_path):
    ok, reason = hooks_mod.run_hooks(
        {"pre_tool": [{"command": "exit 1"}]}, "pre_tool", "anything", {}
    )
    assert not ok


def test_read_tool_hook_gets_readonly_sandbox(monkeypatch):
    selected = []
    monkeypatch.setattr(hooks_mod, "sandbox_command",
                        lambda command, **kwargs: (selected.append(kwargs["writable_workspace"]) or
                                                   (["sandbox", "--", "true"], {})))
    monkeypatch.setattr(hooks_mod.subprocess, "run",
                        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""))
    ok, _ = hooks_mod.run_hooks({"pre_tool": [{"command": "true"}]},
                                 "pre_tool", "read_file", {"path": "a.txt"})
    assert ok and selected == [False]
