"""bash 工具：执行 shell 命令——agent 从「能改文件」升级为「能干活」的一步。

一个 bash 工具带来的能力是组合爆炸式的：跑测试、装依赖、git 操作、运行
刚写好的代码……但它也是最危险的工具，所以有三道防线（CLAUDE.md 第五节）：

    1. 危险命令黑名单：`rm -rf /`、`sudo` 等直接拒绝，连确认的机会都不给；
    2. 用户确认：本工具声明 permission_level="execute"，由权限系统
       （permissions.py）统一在执行前询问用户——M2 时这里曾有一个内置的
       确认钩子，M3 起已拆除，工具只声明危险级别、不自己实现确认（策略
       与机制分离）；
    3. 超时 + 输出截断：超时保护进程不被挂死，截断保护上下文窗口不被一次
       `cat 大文件` 塞爆。

注意 config 用 `from minicode import config` 方式引用而不是 from-import 常量：
这样超时等参数在调用时才取值，测试里可以 monkeypatch config.BASH_TIMEOUT_SECONDS
来快速模拟超时，不用真等 30 秒。
"""

import subprocess
import threading

from minicode import config
from minicode.sandbox import sandbox_command
from minicode.tools.base import Tool

# 教学用的简化黑名单：真实产品（Claude Code）用的是更精细的命令解析 + 规则
# 匹配，这里用子串匹配表达同一个思想——有些操作永远不该让 agent 执行。
BLACKLIST: list[str] = [
    "rm -rf /",
    "rm -rf ~",
    "sudo",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    ":(){",  # fork 炸弹
]


def _truncate(text: str) -> str:
    limit = config.BASH_MAX_OUTPUT_CHARS
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... 输出已截断，共 {len(text)} 字符]"


def _run(tool_input: dict) -> str:
    command = tool_input["command"]

    for banned in BLACKLIST:
        if banned in command:
            return f"错误：命令包含被禁止的操作 {banned!r}，已拒绝执行。请换一种安全的做法。"

    try:
        argv, env = sandbox_command(command)
    except RuntimeError as exc:
        return f"错误：{exc}"
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    captured: dict[str, bytes] = {"stdout": b"", "stderr": b""}
    truncated: dict[str, bool] = {"stdout": False, "stderr": False}

    def drain(label: str, stream: object) -> None:
        assert hasattr(stream, "read")
        limit = config.BASH_MAX_OUTPUT_CHARS * 4
        while chunk := stream.read(4096):
            remaining = limit - len(captured[label])
            if remaining > 0:
                captured[label] += chunk[:remaining]
            if len(chunk) > remaining:
                truncated[label] = True

    threads = [threading.Thread(target=drain, args=(label, stream), daemon=True)
               for label, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))]
    for thread in threads:
        thread.start()
    try:
        proc.wait(timeout=config.BASH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return (
            f"错误：命令执行超过 {config.BASH_TIMEOUT_SECONDS} 秒已被强制终止。"
            "如果是长时间运行的命令，考虑换成能快速返回的等价操作。"
        )
    for thread in threads:
        thread.join(timeout=1)

    stdout = captured["stdout"].decode(errors="replace")
    stderr = captured["stderr"].decode(errors="replace")
    if truncated["stdout"]:
        stdout += "\n[... 输出已截断]"
    if truncated["stderr"]:
        stderr += "\n[... 输出已截断]"

    parts: list[str] = []
    if stdout:
        parts.append(_truncate(stdout))
    if stderr:
        parts.append("stderr:\n" + _truncate(stderr))
    if proc.returncode != 0:
        parts.append(f"命令以非零退出码 {proc.returncode} 结束")

    if not parts:
        return "（命令执行成功，无输出）"
    return "\n".join(parts)


bash_tool = Tool(
    name="bash",
    description=(
        "在用户的机器上执行一条 shell 命令（macOS/Linux），返回 stdout、stderr "
        "和退出码信息。适合用来：运行/验证刚写好的代码、跑测试、安装依赖、"
        "git 操作、查看系统信息。\n"
        f"限制：超过 {config.BASH_TIMEOUT_SECONDS} 秒会被强制终止，所以不要执行"
        "长时间挂起或交互式的命令（如 vim、python 交互解释器）；输出很长时会被"
        "截断。每次执行前用户会看到命令并有权拒绝。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
        },
        "required": ["command"],
    },
    run=_run,
    permission_level="execute",
)
