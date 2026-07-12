"""plan mode 测试：工具集物理切换与恢复、提示词后缀、命令入口。"""

from minicode.agent import Agent
from minicode.cli import handle_slash


class FakeAPI:
    def create(self, **kwargs):
        raise AssertionError("本测试不应发请求")


def test_plan_mode_swaps_to_readonly_tools_and_back():
    agent = Agent(client=FakeAPI())
    full_names = {t.name for t in agent.tools}

    agent.set_plan_mode(True)
    plan_names = {t.name for t in agent.tools}

    assert plan_names == {t for t in full_names if t in ("read_file", "list_files", "glob", "grep", "task", "skill")}
    assert "edit_file" not in plan_names
    assert "bash" not in plan_names
    assert Agent.PLAN_MODE_PROMPT.strip() in agent.system_prompt

    agent.set_plan_mode(False)

    assert {t.name for t in agent.tools} == full_names
    assert Agent.PLAN_MODE_PROMPT.strip() not in agent.system_prompt


def test_plan_mode_idempotent():
    agent = Agent(client=FakeAPI())
    agent.set_plan_mode(True)
    agent.set_plan_mode(True)  # 重复开启不应叠加提示词

    assert agent.system_prompt.count("[计划模式]") == 1


def test_slash_plan_command():
    agent = Agent(client=FakeAPI())

    out_on = handle_slash("/plan on", agent)
    assert agent.plan_mode and "计划模式" in out_on

    out_off = handle_slash("/plan off", agent)
    assert not agent.plan_mode and "退出" in out_off
