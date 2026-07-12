"""system prompt 组装的测试：环境区块内容、AGENT.md 记忆文件的有无，
以及 agent 确实把 system 参数传给了 API。
"""

from datetime import date
from types import SimpleNamespace

from minicode.agent import Agent
from minicode.prompts import build_system_prompt


def test_env_block_contains_cwd_date_and_listing(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "readme.md").write_text("x")

    prompt = build_system_prompt(tmp_path)

    assert str(tmp_path) in prompt
    assert date.today().isoformat() in prompt
    assert "src/" in prompt
    assert "readme.md" in prompt


def test_memory_file_is_injected_when_present(tmp_path):
    (tmp_path / "AGENT.md").write_text("回答用户时永远先说『收到老板』")

    prompt = build_system_prompt(tmp_path)

    assert "收到老板" in prompt
    assert "AGENT.md" in prompt


def test_no_memory_section_when_file_absent(tmp_path):
    prompt = build_system_prompt(tmp_path)

    assert "记忆文件" not in prompt


def test_empty_memory_file_is_ignored(tmp_path):
    (tmp_path / "AGENT.md").write_text("   \n  ")

    prompt = build_system_prompt(tmp_path)

    assert "记忆文件" not in prompt


def test_agent_passes_system_prompt_to_api():
    captured: list[dict] = []

    class FakeAPI:
        def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="好")],
            )

    agent = Agent(client=FakeAPI())
    agent.run_turn("你好")

    assert "system" in captured[0]
    assert "minicode" in captured[0]["system"]
