"""会话持久化：把 messages 存到磁盘，支持 --resume 恢复上次对话。

messages 里的内容块在进入列表前就被转成了普通 dict（见 agent._block_to_dict），
所以这里直接 json.dump 即可——不需要任何自定义序列化逻辑。这是"在边界处
归一化数据"带来的红利。
"""

import json
import time
from pathlib import Path
from typing import Any

SESSION_DIR = Path.home() / ".minicode" / "sessions"


def new_session_path() -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"


def save(path: Path, messages: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"messages": messages}, ensure_ascii=False), encoding="utf-8")


def load_latest() -> list[dict[str, Any]] | None:
    """返回最近一次会话的 messages；没有历史会话时返回 None。"""
    if not SESSION_DIR.is_dir():
        return None
    files = sorted(SESSION_DIR.glob("*.json"))
    if not files:
        return None
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return data["messages"]
