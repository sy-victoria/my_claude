"""skill 系统测试：frontmatter 解析、两级覆盖、渐进式披露、$ARGUMENTS 替换。"""

from pathlib import Path

from minicode import skills
from minicode.prompts import build_system_prompt
from minicode.tools.skill import skill_tool


def _make_skill(root: Path, name: str, description: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8"
    )


def test_parse_frontmatter_and_body(tmp_path):
    _make_skill(tmp_path, "demo", "演示用", "第一步做 X\n$ARGUMENTS")

    found = skills._scan_dir(tmp_path)

    assert found["demo"].description == "演示用"
    assert "第一步做 X" in found["demo"].load_body()


def test_project_overrides_user_skill(tmp_path, monkeypatch):
    user_dir = tmp_path / "user" / ".minicode" / "skills"
    project = tmp_path / "proj"
    _make_skill(user_dir, "commit", "用户级版本", "用户级正文")
    _make_skill(project / ".minicode" / "skills", "commit", "项目级版本", "项目级正文")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "user")

    found = skills.discover_skills(project)

    assert found["commit"].description == "项目级版本"


def test_index_has_description_but_not_body(tmp_path):
    _make_skill(tmp_path / ".minicode" / "skills", "deploy", "部署项目", "秘密正文步骤")

    index = skills.skills_index(skills.discover_skills(tmp_path))

    assert "deploy" in index and "部署项目" in index
    assert "秘密正文步骤" not in index  # 渐进式披露：清单不含正文


def test_system_prompt_contains_index_not_body(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    _make_skill(tmp_path / ".minicode" / "skills", "deploy", "部署项目", "秘密正文步骤")

    prompt = build_system_prompt(tmp_path)

    assert "deploy" in prompt
    assert "秘密正文步骤" not in prompt


def test_render_replaces_arguments(tmp_path):
    _make_skill(tmp_path, "demo", "演示", "执行任务，要求：$ARGUMENTS")

    found = skills._scan_dir(tmp_path)
    rendered = skills.render_skill(found["demo"], "只改注释")

    assert "要求：只改注释" in rendered


def test_skill_tool_returns_body(tmp_path, monkeypatch):
    _make_skill(tmp_path / ".minicode" / "skills", "demo", "演示", "正文内容")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.chdir(tmp_path)

    result = skill_tool.run({"name": "demo"})

    assert "正文内容" in result


def test_skill_tool_unknown_name_lists_available(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.chdir(tmp_path)

    result = skill_tool.run({"name": "nope"})

    assert "错误" in result
