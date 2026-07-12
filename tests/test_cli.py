"""cli 入口的基本测试：缺 API key 时的行为。

slash 命令、会话持久化、中断回滚等 M8 功能的测试在
tests/test_session_and_cli.py。
"""

import pytest

from minicode.cli import main


def test_main_exits_when_api_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["minicode"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
