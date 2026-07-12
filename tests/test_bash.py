"""bash 工具的纯逻辑测试：覆盖正常执行、非零退出、超时、截断、黑名单、用户拒绝。

所有需要"用户确认"的用例都通过 monkeypatch 替换模块级钩子
ask_user_confirmation，不依赖真实终端输入。
超时用例通过 monkeypatch 把 config.BASH_TIMEOUT_SECONDS 调小，
不用真等 30 秒。
"""

import pytest

from minicode import config
from minicode.tools import bash
from minicode.tools.bash import bash_tool


@pytest.fixture
def auto_confirm(monkeypatch):
    monkeypatch.setattr(bash, "ask_user_confirmation", lambda command: True)


def test_normal_command_returns_stdout(auto_confirm):
    result = bash_tool.run({"command": "echo hello"})

    assert "hello" in result


def test_nonzero_exit_code_is_reported(auto_confirm):
    result = bash_tool.run({"command": "exit 3"})

    assert "3" in result
    assert "退出码" in result


def test_stderr_is_captured(auto_confirm):
    result = bash_tool.run({"command": "echo oops >&2"})

    assert "stderr" in result
    assert "oops" in result


def test_timeout_returns_readable_error(auto_confirm, monkeypatch):
    monkeypatch.setattr(config, "BASH_TIMEOUT_SECONDS", 1)

    result = bash_tool.run({"command": "sleep 5"})

    assert "超过 1 秒" in result


def test_long_output_is_truncated(auto_confirm):
    result = bash_tool.run({"command": "python3 -c \"print('x' * 5000)\""})

    assert "输出已截断" in result
    # 截断后的总长度应该在限制值附近，而不是原始的 5000+。
    assert len(result) < config.BASH_MAX_OUTPUT_CHARS + 100


def test_blacklisted_command_is_rejected_without_confirmation(monkeypatch):
    confirm_calls: list[str] = []
    monkeypatch.setattr(
        bash, "ask_user_confirmation", lambda command: confirm_calls.append(command) or True
    )

    result = bash_tool.run({"command": "sudo rm -rf /tmp/x"})

    assert "禁止" in result
    # 黑名单命中时连确认环节都不应该进入。
    assert confirm_calls == []


def test_user_denial_returns_guidance_to_model(monkeypatch):
    monkeypatch.setattr(bash, "ask_user_confirmation", lambda command: False)

    result = bash_tool.run({"command": "echo hi"})

    assert "拒绝" in result


def test_no_output_command_reports_success(auto_confirm):
    result = bash_tool.run({"command": "true"})

    assert "成功" in result
