"""终端交互入口：rich 渲染 + 流式输出 + slash 命令 + 会话持久化 + 中断处理。

M8 之前这里是一个 print/input 的朴素 REPL；现在的结构：
    main()            解析参数、组装 Agent、进入主循环
    _run_one_turn()   跑一轮对话：spinner 等待、流式渲染、Ctrl+C 回滚
    handle_slash()    所有 / 命令的分发（纯函数风格，方便测试）
"""

import argparse
import os
import random
import sys

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner

from minicode import session, skills
from minicode.agent import Agent
from minicode.config import DEFAULT_TIER, TIER_MODELS, resolve_model
from minicode.permissions import MODES, PermissionManager

console = Console()

# Claude Code 的灵魂彩蛋：等待模型时随机显示一个动名词。
SPINNER_VERBS = [
    "Musing", "Pondering", "Brewing", "Scheming", "Noodling", "Percolating",
    "Ruminating", "Tinkering", "Vibing", "Cogitating", "Simmering", "Mulling",
    "Marinating", "Whirring", "Conjuring", "Sketching", "Weaving", "Polishing",
    "Hatching", "Doodling", "Daydreaming", "Wrangling",
]

HELP_TEXT = """\
可用命令：
  /help             显示本帮助
  /clear            清空当前对话历史
  /compact          手动压缩上下文
  /cost             显示 token 用量
  /mode <模式>      切换权限模式（default / accept-edits / yolo）
  /model <档位>     切换模型档位（sonnet / opus）
  /plan on|off      计划模式（只读调研出方案，批准后再执行）
  exit 或 Ctrl+D    退出"""


def handle_slash(command: str, agent: Agent) -> str:
    """处理一条 slash 命令，返回要显示给用户的文本。"""
    parts = command.split()
    name, args = parts[0], parts[1:]

    if name == "/help":
        return HELP_TEXT
    if name == "/clear":
        agent.messages.clear()
        agent.context.last_input_tokens = 0
        return "对话历史已清空。"
    if name == "/compact":
        return "已手动压缩上下文。" if agent.compact() else "对话还很短，无需压缩。"
    if name == "/cost":
        return (
            f"当前上下文约 {agent.context.last_input_tokens} tokens，"
            f"本会话累计消耗 {agent.context.cumulative_tokens} tokens。"
        )
    if name == "/mode":
        if not args or args[0] not in MODES:
            return f"用法：/mode {'|'.join(MODES)}（当前：{agent.permissions.mode}）"
        agent.permissions.mode = args[0]
        return f"权限模式已切换为 {args[0]}。"
    if name == "/model":
        if not args or args[0] not in TIER_MODELS:
            return f"用法：/model {'|'.join(TIER_MODELS)}（当前模型：{agent.model}）"
        agent.model = resolve_model(args[0])
        return f"模型已切换为 {args[0]} 档位（{agent.model}），下一次请求生效。"
    if name == "/plan":
        if not args or args[0] not in ("on", "off"):
            return f"用法：/plan on|off（当前：{'on' if agent.plan_mode else 'off'}）"
        agent.set_plan_mode(args[0] == "on")
        return (
            "已进入计划模式：agent 只能调研和出方案，批准后 /plan off 再执行。"
            if agent.plan_mode
            else "已退出计划模式，agent 恢复完整工具集。"
        )
    return f"未知命令 {name}，输入 /help 查看可用命令。"


def resolve_skill_input(user_input: str) -> str | None:
    """如果输入是 /skill名 [参数]，渲染 skill 正文作为本轮用户消息返回。

    这是 skill 的"用户触发"路径：/commit 修复登录bug -> commit skill 的
    正文（$ARGUMENTS 已替换为"修复登录bug"）。不是 skill 则返回 None。
    """
    parts = user_input.split(maxsplit=1)
    name = parts[0][1:]
    found = skills.discover_skills().get(name)
    if found is None:
        return None
    arguments = parts[1] if len(parts) > 1 else ""
    return skills.render_skill(found, arguments)


def _run_one_turn(agent: Agent, user_input: str) -> None:
    """跑一轮对话：spinner 等首字、流式渲染 markdown、Ctrl+C 回滚。

    中断回滚的原因：如果在模型回复到一半时打断，messages 会停在"有用户
    输入、没有 assistant 回复"的非法状态，下一轮请求会因角色不交替而出错。
    所以记录轮次开始时的消息数，中断时把本轮追加的消息全部丢弃。
    """
    checkpoint = len(agent.messages)
    accumulated = ""
    verb = random.choice(SPINNER_VERBS)

    try:
        with Live(Spinner("dots", text=f"{verb}…"), console=console, refresh_per_second=8) as live:
            def on_text(chunk: str) -> None:
                nonlocal accumulated
                accumulated += chunk
                live.update(Markdown(accumulated))

            reply = agent.run_turn(user_input, on_text=on_text)
            live.update(Markdown(reply if reply else accumulated))
    except KeyboardInterrupt:
        del agent.messages[checkpoint:]
        console.print("\n[yellow](已中断，本轮输入已丢弃)[/yellow]")
        return

    console.print(f"[dim]  context: {agent.context.last_input_tokens} tokens[/dim]")


def _print_tool_call(name: str, tool_input: dict) -> None:
    console.print(f"  [cyan]> {name}[/cyan][dim]({str(tool_input)[:120]})[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(prog="minicode")
    parser.add_argument("--tier", default=DEFAULT_TIER, choices=list(TIER_MODELS), help="模型档位")
    parser.add_argument("--mode", default="default", choices=list(MODES), help="权限模式")
    parser.add_argument("--resume", action="store_true", help="恢复最近一次会话")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误：请先设置环境变量 ANTHROPIC_API_KEY")
        sys.exit(1)

    console.print(
        f"[bold]minicode[/bold] —— 从零复现的 Claude Code 风格 coding agent\n"
        f"[dim]档位 {args.tier} · 权限 {args.mode} · /help 查看命令[/dim]"
    )
    if args.mode == "yolo":
        console.print("[red]⚠ yolo 模式：所有工具调用不经确认直接执行[/red]")

    # MCP 工具在入口加载一次（而不是在 Agent 里），混入本地工具集；
    # agent 循环对两者一视同仁。
    from minicode.mcp_client import load_mcp_tools
    from minicode.tools import TOOLS

    mcp_tools = load_mcp_tools()
    if mcp_tools:
        console.print(f"[dim]已加载 {len(mcp_tools)} 个 MCP 工具：{', '.join(t.name for t in mcp_tools)}[/dim]")

    agent = Agent(
        api_key=api_key,
        tier=args.tier,
        on_tool_call=_print_tool_call,
        permissions=PermissionManager(mode=args.mode),
        tools=TOOLS + mcp_tools,
    )
    agent.on_compact = lambda b, a: console.print(f"[dim]  ⚙ 上下文已压缩：{b} -> {a} 条消息[/dim]")

    if args.resume:
        restored = session.load_latest()
        if restored:
            agent.messages = restored
            console.print(f"[dim]已恢复上次会话（{len(restored)} 条消息）[/dim]")
        else:
            console.print("[dim]没有可恢复的会话，从新对话开始[/dim]")

    session_path = session.new_session_path()

    while True:
        try:
            user_input = input("\n> ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue  # 输入提示符下的 Ctrl+C 只清空当前行，不退出

        if user_input in ("exit", "quit"):
            break
        if not user_input:
            continue
        if user_input.startswith("/"):
            # 先查内置命令，再查 skill（/commit 这类），都没有才报未知
            builtin = {"/help", "/clear", "/compact", "/cost", "/mode", "/model", "/plan"}
            if user_input.split()[0] in builtin:
                console.print(handle_slash(user_input, agent))
                continue
            rendered = resolve_skill_input(user_input)
            if rendered is None:
                console.print(handle_slash(user_input, agent))  # 输出"未知命令"
                continue
            user_input = rendered  # skill 正文作为本轮用户消息，走正常对话

        _run_one_turn(agent, user_input)
        session.save(session_path, agent.messages)


if __name__ == "__main__":
    main()
