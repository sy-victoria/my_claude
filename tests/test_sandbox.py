"""未支持的平台必须拒绝启动本地执行进程。"""

import os

import pytest

from minicode.sandbox import sandbox_command


@pytest.mark.skipif(os.name == "posix", reason="Linux 用集成测试验证 bubblewrap")
def test_unsupported_platform_rejects_shell():
    with pytest.raises(RuntimeError, match="沙箱"):
        sandbox_command("echo hello")
