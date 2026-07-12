"""bash 工具的纯逻辑测试：正常执行、非零退出、超时、截断、黑名单。

用户确认已不在本工具内（M3 起由权限系统统一负责，见 test_permissions.py），
所以这里只测命令执行本身。
超时用例通过 monkeypatch 把 config.BASH_TIMEOUT_SECONDS 调小，不用真等 30 秒。
"""

from minicode import config
from minicode.tools.bash import bash_tool


def test_normal_command_returns_stdout():
    result = bash_tool.run({"command": "echo hello"})

    assert "hello" in result


def test_nonzero_exit_code_is_reported():
    result = bash_tool.run({"command": "exit 3"})

    assert "3" in result
    assert "退出码" in result


def test_stderr_is_captured():
    result = bash_tool.run({"command": "echo oops >&2"})

    assert "stderr" in result
    assert "oops" in result


def test_timeout_returns_readable_error(monkeypatch):
    monkeypatch.setattr(config, "BASH_TIMEOUT_SECONDS", 1)

    result = bash_tool.run({"command": "sleep 5"})

    assert "超过 1 秒" in result


def test_long_output_is_truncated():
    result = bash_tool.run({"command": "python3 -c \"print('x' * 5000)\""})

    assert "输出已截断" in result
    assert len(result) < config.BASH_MAX_OUTPUT_CHARS + 100


def test_blacklisted_command_is_rejected():
    result = bash_tool.run({"command": "sudo rm -rf /tmp/x"})

    assert "禁止" in result


def test_no_output_command_reports_success():
    result = bash_tool.run({"command": "true"})

    assert "成功" in result


def test_bash_declares_execute_permission_level():
    assert bash_tool.permission_level == "execute"
