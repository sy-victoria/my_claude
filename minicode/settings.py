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
        if is_project and ("base_url" in data or "provider" in data):
            field = "base_url" if "base_url" in data else "provider"
            raise ValueError(f"项目设置不能指定 {field}：{path}")
        for key in ("base_url", "provider", "model", "max_loops", "api_timeout_seconds", "max_turn_seconds", "max_tool_calls"):
            if key in data:
                if key == "max_loops" and (
                    not isinstance(data[key], int) or isinstance(data[key], bool) or data[key] < 1
                ):
                    raise ValueError(f"max_loops 必须是正整数：{path}")
                if is_project and key in {"api_timeout_seconds", "max_turn_seconds", "max_tool_calls"}:
                    raise ValueError(f"项目设置不能指定 {key}：{path}")
                if is_project and key == "max_loops" and key in settings:
                    settings[key] = min(settings[key], data[key])
                else:
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
