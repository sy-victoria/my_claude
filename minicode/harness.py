"""Durable task checkpoints and conservative rollback for agent file edits."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

TASK_DIR = Path.home() / ".minicode" / "tasks"
MAX_SNAPSHOT_BYTES = 20_000_000


def _digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".task-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class TaskJournal:
    """One task owns its messages, tool receipts and original file contents."""

    def __init__(self, task_id: str, workspace: Path, root: Path = TASK_DIR,
                 existing: bool = False) -> None:
        if not task_id or any(char not in "0123456789abcdef" for char in task_id):
            raise ValueError("无效任务 ID")
        self.task_id = task_id
        self.workspace = workspace.resolve()
        self.directory = root / task_id
        self.path = self.directory / "checkpoint.json"
        if existing:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if Path(self.data["workspace"]).resolve() != self.workspace:
                raise ValueError("任务工作区与当前目录不一致")
        else:
            self.directory.mkdir(parents=True, exist_ok=False)
            if os.name != "nt":
                self.directory.chmod(0o700)
            self.data: dict[str, Any] = {"version": 1, "workspace": str(self.workspace),
                                         "status": "active", "messages": [], "tools": {},
                                         "writes": [], "events": []}
            self._save()

    @classmethod
    def create(cls, workspace: Path, root: Path = TASK_DIR) -> TaskJournal:
        return cls(uuid.uuid4().hex, workspace, root)

    @classmethod
    def load(cls, task_id: str, workspace: Path, root: Path = TASK_DIR) -> TaskJournal:
        return cls(task_id, workspace, root, existing=True)

    def _save(self) -> None:
        _atomic_bytes(self.path, json.dumps(self.data, ensure_ascii=False).encode("utf-8"))

    def checkpoint(self, messages: list[dict[str, Any]], event: str) -> None:
        self.data["messages"] = messages
        self.data["events"].append({"event": event, "sequence": len(self.data["events"])})
        self._save()

    def set_status(self, status: str) -> None:
        self.data["status"] = status
        self._save()

    def receipt(self, call_id: str) -> str | None:
        item = self.data["tools"].get(call_id)
        if item is None:
            return None
        if item["status"] == "done":
            return item["result"]
        return "工具上次执行状态不明，已禁止自动重放；请检查工作区后重新下达操作"

    def begin_tool(self, call_id: str, name: str, tool_input: dict[str, Any]) -> str | None:
        item = self.data["tools"].get(call_id)
        if item is not None and (item["name"] != name or item["input"] != tool_input):
            raise ValueError("工具调用 ID 与已记录的操作不一致")
        previous = self.receipt(call_id)
        if previous is not None:
            return previous
        self.data["tools"][call_id] = {"name": name, "input": tool_input, "status": "running"}
        self.data["events"].append({"event": "tool_begin", "call_id": call_id})
        self._save()
        return None

    def before_write(self, call_id: str, path: Path) -> None:
        target = path.resolve()
        if not target.is_relative_to(self.workspace):
            raise ValueError("快照目标不在工作区")
        if target.exists() and target.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("文件超过 20 MB 快照上限，拒绝在可回滚任务中修改")
        original = target.read_bytes() if target.exists() else None
        snapshot = self.directory / "snapshots" / f"{len(self.data['writes'])}.bin"
        if original is not None:
            _atomic_bytes(snapshot, original)
        self.data["writes"].append({"call_id": call_id, "path": str(target),
                                     "before_hash": _digest(original),
                                     "snapshot": str(snapshot) if original is not None else None,
                                     "after_hash": None})
        self._save()

    def finish_tool(self, call_id: str, result: str) -> None:
        for write in self.data["writes"]:
            if write["call_id"] == call_id and write["after_hash"] is None:
                target = Path(write["path"])
                if not target.resolve().is_relative_to(self.workspace):
                    raise ValueError("文件目标已移出工作区")
                write["after_hash"] = _digest(target.read_bytes() if target.exists() else None)
                write["finished"] = True
        self.data["tools"][call_id].update(status="done", result=result)
        self.data["events"].append({"event": "tool_done", "call_id": call_id})
        self._save()

    def recover_messages(self) -> list[dict[str, Any]]:
        messages = list(self.data["messages"])
        if messages and messages[-1]["role"] == "assistant":
            blocks = [block for block in messages[-1]["content"]
                      if block.get("type") == "tool_use"]
            if blocks:
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block["id"],
                     "content": self.receipt("main:" + block["id"])
                     if self.receipt("main:" + block["id"]) is not None
                     else "工具上次执行状态不明，已禁止自动重放；请检查工作区后重新下达操作"}
                    for block in blocks]})
                self.checkpoint(messages, "recover_pending")
        return messages

    def rollback(self) -> list[str]:
        conflicts: list[str] = []
        blocked: set[str] = set()
        for write in reversed(self.data["writes"]):
            target = Path(write["path"])
            if str(target) in blocked:
                continue
            if not target.resolve().is_relative_to(self.workspace):
                conflicts.append(str(target))
                blocked.add(str(target))
                continue
            current = _digest(target.read_bytes() if target.exists() else None)
            if not write.get("finished") or current != write["after_hash"]:
                conflicts.append(str(target))
                blocked.add(str(target))
                continue
            snapshot = write["snapshot"]
            if snapshot is None:
                target.unlink(missing_ok=True)
            else:
                _atomic_bytes(target, Path(snapshot).read_bytes())
        self.data["status"] = "rollback_conflict" if conflicts else "rolled_back"
        self.data["events"].append({"event": "rollback", "conflicts": conflicts})
        self._save()
        return conflicts
