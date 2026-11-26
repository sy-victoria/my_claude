"""Failure recovery, duplicate suppression and safe file rollback."""

from pathlib import Path

from minicode.harness import TaskJournal


def test_completed_tool_is_recovered_without_reexecution(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    journal = TaskJournal.create(workspace, tmp_path / "tasks")
    messages = [{"role": "user", "content": "go"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "a",
                   "name": "write_file", "input": {"path": "a.py"}}]}]
    journal.checkpoint(messages, "model_response")
    assert journal.begin_tool("main:a", "write_file", {"path": "a.py"}) is None
    journal.finish_tool("main:a", "written")
    loaded = TaskJournal.load(journal.task_id, workspace, tmp_path / "tasks")
    recovered = loaded.recover_messages()
    assert recovered[-1]["content"][0]["content"] == "written"
    assert loaded.begin_tool("main:a", "write_file", {"path": "a.py"}) == "written"


def test_running_write_is_not_replayed_and_conflict_is_preserved(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    target = workspace / "a.py"
    target.write_text("before")
    journal = TaskJournal.create(workspace, tmp_path / "tasks")
    journal.begin_tool("a", "write_file", {"path": "a.py"})
    journal.before_write("a", target)
    target.write_text("unknown change")
    loaded = TaskJournal.load(journal.task_id, workspace, tmp_path / "tasks")
    assert "禁止自动重放" in loaded.receipt("a")
    assert loaded.rollback() == [str(target)]
    assert target.read_text() == "unknown change"


def test_rollback_reverses_agent_edits_but_not_later_user_change(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    first = workspace / "first.py"
    second = workspace / "second.py"
    first.write_text("old")
    journal = TaskJournal.create(workspace, tmp_path / "tasks")
    for call_id, target, new in (("one", first, "new"), ("two", second, "created")):
        journal.begin_tool(call_id, "write_file", {"path": target.name})
        journal.before_write(call_id, target)
        target.write_text(new)
        journal.finish_tool(call_id, "done")
    second.write_text("user edit")
    assert journal.rollback() == [str(second)]
    assert first.read_text() == "old"
    assert second.read_text() == "user edit"


def test_rollback_removes_new_agent_file(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    path = workspace / "new.py"
    journal = TaskJournal.create(workspace, tmp_path / "tasks")
    journal.begin_tool("one", "write_file", {"path": "new.py"})
    journal.before_write("one", path)
    path.write_text("created")
    journal.finish_tool("one", "done")
    assert journal.rollback() == []
    assert not path.exists()


def test_recovered_pending_tool_results_continue_without_duplicate_user(tmp_path):
    from types import SimpleNamespace

    from minicode.agent import Agent
    from minicode.permissions import PermissionManager

    workspace = tmp_path / "repo"
    workspace.mkdir()
    journal = TaskJournal.create(workspace, tmp_path / "tasks")
    messages = [{"role": "user", "content": "edit"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "a",
                   "name": "write_file", "input": {"path": "a.py"}}]}]
    journal.checkpoint(messages, "model_response")
    journal.begin_tool("main:a", "write_file", {"path": "a.py"})
    journal.finish_tool("main:a", "已创建 a.py")
    loaded = TaskJournal.load(journal.task_id, workspace, tmp_path / "tasks")

    class Client:
        def create(self, **kwargs):
            assert len(kwargs["messages"]) == 3
            assert kwargs["messages"][-1]["content"][0]["tool_use_id"] == "a"
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="done")])

    agent = Agent(client=Client(), permissions=PermissionManager(cwd=workspace), journal=loaded)
    agent.messages = loaded.recover_messages()
    assert agent.run_turn("", resume_pending=True) == "done"
