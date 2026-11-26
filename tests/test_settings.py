"""设置优先级与项目权限边界。"""

import json

from minicode.settings import load_settings


def test_project_cannot_grant_its_own_allow_rules(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".minicode").mkdir(parents=True)
    (project / ".minicode").mkdir(parents=True)
    (home / ".minicode" / "settings.json").write_text(
        json.dumps({"model": "user-model", "permissions": {"allow": ["bash:git status"]}}), encoding="utf-8"
    )
    (project / ".minicode" / "settings.json").write_text(
        json.dumps({"model": "project-model", "permissions": {"allow": ["bash:rm -rf ."],
                                                         "deny": ["bash:rm -rf ."]}}), encoding="utf-8"
    )
    monkeypatch.setattr("minicode.settings.Path.home", lambda: home)
    settings = load_settings(project)
    assert settings["model"] == "project-model"
    assert settings["permissions"]["allow"] == ["bash:git status"]
    assert settings["permissions"]["deny"] == ["bash:rm -rf ."]
