"""cli 的测试：只测非交互部分（欢迎语内容、缺 API key 时的报错行为）。

真正的 REPL 循环需要标准输入交互和真实 API 调用，留给 devlog 里记录的
人工对话验收，不在这里用测试覆盖。
"""

import pytest

from minicode.cli import WELCOME, main
from minicode.config import DEFAULT_TIER


def test_welcome_mentions_default_tier() -> None:
    assert DEFAULT_TIER in WELCOME


def test_main_exits_when_api_key_missing(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["minicode"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
