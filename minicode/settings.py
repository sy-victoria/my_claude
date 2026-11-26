"""读取用户与项目设置；项目配置不能自行扩大工具权限。"""

import json
from pathlib import Path
from typing import Any


def load_settings(cwd: Path | None = None) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    user_file = Path.home() / ".minicode" / "settings.json"
    project_file = root / ".minicode" / "settings.json"
    settings: dict[str, Any] = {"permissions": {"allow": [], "ask": [], "deny": []}}
    for path, is_project in ((user_file, False), (project_file, True)):
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"设置文件必须是 JSON 对象：{path}")
        # 项目文件可随仓库传播，不能决定接收用户 API Key 的服务端。
        if is_project and "base_url" in data:
            raise ValueError(f"项目设置不能指定 base_url：{path}")
        for key in ("base_url", "model", "max_loops"):
            if key in data:
                settings[key] = data[key]
        rules = data.get("permissions", {})
        if not isinstance(rules, dict):
            raise ValueError(f"permissions 必须是 JSON 对象：{path}")
        for verdict in ("allow", "ask", "deny"):
            entries = rules.get(verdict, [])
            if not isinstance(entries, list) or not all(isinstance(x, str) for x in entries):
                raise ValueError(f"无效权限规则 {verdict}：{path}")
            if not is_project or verdict != "allow":
                settings["permissions"][verdict].extend(entries)
    return settings
