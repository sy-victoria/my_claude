"""M0 冒烟测试：确认欢迎语能正常打印，且引用了正确的默认档位。"""

from minicode.cli import WELCOME, main
from minicode.config import DEFAULT_TIER


def test_welcome_mentions_default_tier() -> None:
    assert DEFAULT_TIER in WELCOME


def test_main_runs_without_error(capsys) -> None:
    main()
    captured = capsys.readouterr()
    assert "minicode" in captured.out
