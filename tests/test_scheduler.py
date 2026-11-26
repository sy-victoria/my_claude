"""Read concurrency and write barriers preserve the model's result order."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from minicode.agent import Agent, _accesses_conflict
from minicode.permissions import PermissionManager
from minicode.tools.base import Tool


def test_path_conflict_detects_parent_and_child(tmp_path):
    root = Path(tmp_path)
    assert _accesses_conflict((root, False), (root / "a.py", True))
    assert not _accesses_conflict((root / "a.py", False), (root / "a.py", False))
    assert not _accesses_conflict((root / "a.py", True), (root / "b.py", False))


def test_reads_overlap_but_write_is_barrier(tmp_path, monkeypatch):
    tools = [Tool("read_file", "", {}, lambda _input: "", "read"),
             Tool("write_file", "", {}, lambda _input: "", "write")]
    agent = Agent(client=object(), tools=tools,
                  permissions=PermissionManager(mode="accept-edits", cwd=tmp_path))
    active = 0
    peak = 0
    seen = []
    lock = threading.Lock()

    def fake_run(name, tool_input, approved=False):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            seen.append(("start", name, tool_input["path"]))
        time.sleep(0.03)
        with lock:
            active -= 1
            seen.append(("end", name, tool_input["path"]))
        return tool_input["path"]

    monkeypatch.setattr(agent, "_run_tool", fake_run)
    blocks = [SimpleNamespace(id=str(i), name=name, input={"path": str(i)})
              for i, name in enumerate(("read_file", "read_file", "write_file", "read_file"))]
    results, count, limited = agent._dispatch_tool_blocks(blocks, 10, time.monotonic() + 5)
    assert peak == 2
    assert [item["content"] for item in results] == ["0", "1", "2", "3"]
    assert seen.index(("end", "read_file", "1")) < seen.index(("start", "write_file", "2"))
    assert count == 4 and not limited
