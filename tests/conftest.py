"""单元测试隔离模型循环与文件工具，Docker 集成测试可显式启用真实执行。"""

import os

import pytest

from minicode.agent import Agent


@pytest.fixture(autouse=True)
def file_tool_unit_runner(monkeypatch):
    if os.name == "nt" and os.environ.get("MINICODE_TEST_DOCKER") != "1":
        monkeypatch.setattr(Agent, "_run_file_tool",
                            lambda self, name, tool_input: self._tools_by_name[name].run(tool_input))
