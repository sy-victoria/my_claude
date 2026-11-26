"""设置优先级与项目权限边界。"""

import json

import pytest

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


def test_project_cannot_redirect_api_key_to_another_endpoint(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".minicode").mkdir(parents=True)
    (project / ".minicode").mkdir(parents=True)
    (home / ".minicode" / "settings.json").write_text(
        json.dumps({"base_url": "https://api.example.com"}), encoding="utf-8"
    )
    (project / ".minicode" / "settings.json").write_text(
        json.dumps({"base_url": "https://attacker.example"}), encoding="utf-8"
    )
    monkeypatch.setattr("minicode.settings.Path.home", lambda: home)
    with pytest.raises(ValueError, match="项目设置不能指定 base_url"):
        load_settings(project)


def test_project_cannot_expand_runtime_budget(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".minicode").mkdir(parents=True)
    (project / ".minicode").mkdir(parents=True)
    (home / ".minicode" / "settings.json").write_text(
        json.dumps({"max_loops": 5, "max_tool_calls": 10}), encoding="utf-8")
    project_settings = project / ".minicode" / "settings.json"
    monkeypatch.setattr("minicode.settings.Path.home", lambda: home)

    project_settings.write_text(json.dumps({"max_loops": 50}), encoding="utf-8")
    assert load_settings(project)["max_loops"] == 5
    project_settings.write_text(json.dumps({"max_loops": 3}), encoding="utf-8")
    assert load_settings(project)["max_loops"] == 3
    project_settings.write_text(json.dumps({"max_tool_calls": 100}), encoding="utf-8")
    with pytest.raises(ValueError, match="项目设置不能指定 max_tool_calls"):
        load_settings(project)


def test_project_cannot_select_credential_provider(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".minicode").mkdir(parents=True)
    (project / ".minicode").mkdir(parents=True)
    monkeypatch.setattr("minicode.settings.Path.home", lambda: home)
    (project / ".minicode" / "settings.json").write_text(
        json.dumps({"provider": "openai"}), encoding="utf-8")
    with pytest.raises(ValueError, match="项目设置不能指定 provider"):
        load_settings(project)
