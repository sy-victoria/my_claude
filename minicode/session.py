"""会话持久化：把 messages 存到磁盘，支持 --resume 恢复上次对话。

messages 里的内容块在进入列表前就被转成了普通 dict（见 agent._block_to_dict），
所以这里直接 json.dump 即可——不需要任何自定义序列化逻辑。这是"在边界处
归一化数据"带来的红利。
"""

import json
import os
import time
import tempfile
import uuid
from pathlib import Path
from typing import Any

SESSION_DIR = Path.home() / ".minicode" / "sessions"


def new_session_path() -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.json"


def save(path: Path, messages: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"messages": messages}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def list_sessions(limit: int = 10) -> list[Path]:
    """列出最近的会话文件，最新的排最前面（供 /resume 交互式选择用）。"""
    if not SESSION_DIR.is_dir():
        return []
    files = sorted(SESSION_DIR.glob("*.json"), reverse=True)
    return files[:limit]


def load(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["messages"]


def preview(path: Path) -> str:
    """从会话文件里摘一句第一条用户消息，给 /resume 列表做预览用。"""
    messages = load(path)
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message["content"]
        text = content if isinstance(content, str) else next(
            (b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"), ""
        )
        text = text.strip()
        if text:
            return text[:40] + ("…" if len(text) > 40 else "")
    return "（空会话）"


def load_latest() -> list[dict[str, Any]] | None:
    """返回最近一次会话的 messages；没有历史会话时返回 None。"""
    files = list_sessions(limit=1)
    return load(files[0]) if files else None
