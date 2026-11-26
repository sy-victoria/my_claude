"""终端交互入口：rich 渲染 + 流式输出 + slash 命令 + 会话持久化 + 中断处理。

M8 之前这里是一个 print/input 的朴素 REPL；现在的结构：
    main()            解析参数、组装 Agent、进入主循环
    _run_one_turn()   跑一轮对话：spinner 等待、流式渲染、Ctrl+C 回滚
    handle_slash()    所有 / 命令的分发（纯函数风格，方便测试）
"""

import argparse
import difflib
import json
import os
import random
import re
import sys
from pathlib import Path

try:
    import readline  # 标准库，不是新依赖；Windows 没有这个模块，静默跳过补全即可
except ImportError:
    readline = None

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.theme import Theme

from minicode import session, skills
from minicode.agent import Agent
from minicode.config import CONTEXT_WINDOW_TOKENS, DEFAULT_TIER, TIER_MODELS, resolve_model
from minicode.permissions import MODES, PermissionManager
from minicode.settings import load_settings

# 配色跟着后端走：我们接的是 DeepSeek，就用 DeepSeek 的品牌蓝，
# 而不是 Anthropic 的橙色——终端主题应该诚实反映"这是谁的模型在跑"。
THEME = Theme({
    "banner": "bold #4D6BFE",     # DeepSeek 主品牌蓝，用于标题
    "accent": "#4D6BFE",          # 深蓝：交互提示符、spinner
    "secondary": "#8FB3FF",       # 浅蓝：次要信息（档位、上下文用量）
    "tool": "#8FB3FF",            # 工具调用日志
    "warn": "bold red",
})
console = Console(theme=THEME)

# 终端里的小宠物：一头跟着 DeepSeek 品牌走的鲸鱼，等待模型时"游"在 spinner 旁边。
MASCOT = "🐳"

# Claude Code 的灵魂彩蛋：等待模型时随机显示一个动名词。
SPINNER_VERBS = [
    "Musing", "Pondering", "Brewing", "Scheming", "Noodling", "Percolating",
    "Ruminating", "Tinkering", "Vibing", "Cogitating", "Simmering", "Mulling",
    "Marinating", "Whirring", "Conjuring", "Sketching", "Weaving", "Polishing",
    "Hatching", "Doodling", "Daydreaming", "Wrangling",
]

BUILTIN_COMMANDS = ("/help", "/clear", "/compact", "/cost", "/mode", "/model", "/plan", "/resume")

HELP_TEXT = """\
可用命令：
  /help             显示本帮助
  /clear            清空当前对话历史
  /compact          手动压缩上下文
  /cost             显示 token 用量
  /mode             交互式切换权限模式（不带参数弹出列表；也可 /mode <模式> 直接切）
  /model            交互式选择模型档位（不带参数弹出列表；也可 /model <档位> 直接切）
  /plan             交互式切换计划模式（不带参数弹出列表；也可 /plan on|off 直接切）
  /resume           从历史会话里选一个恢复（当前对话会被替换）
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
            return f"用法：/model {'|'.join(TIER_MODELS)}（当前模型：{agent.tier}，{agent.model}）"
        agent.tier = args[0]
        agent.model = resolve_model(args[0])
        return f"模型已切换为 {args[0]} 档位（{agent.model}），下一次请求生效。"
    if name == "/resume":
        return "用法：/resume（不带参数，从列表中选择要恢复的历史会话）"
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


def _prompt_from_list(options: list[tuple[str, str]], current: str, question: str) -> str:
    """通用编号选择菜单：options 是 (值, 展示文案) 列表，返回选中的值。

    /model /mode /plan 三个交互式命令共用这份渲染逻辑，避免三份几乎一样的
    代码——它们的差异只是"有哪些选项、每项怎么解释"，选择与渲染的机制相同。
    """
    values = [v for v, _ in options]
    for i, (value, label) in enumerate(options, start=1):
        mark = " [accent](当前)[/accent]" if value == current else ""
        console.print(f"  [accent]{i}[/accent]. {label}{mark}")
    choice = Prompt.ask(
        question,
        choices=[str(i) for i in range(1, len(values) + 1)],
        default=str(values.index(current) + 1),
        console=console,
    )
    return values[int(choice) - 1]


def prompt_model_choice(agent: Agent) -> str:
    """/model 不带参数时的交互式选择列表，返回选中的档位名。

    handle_slash 保持纯函数（好测试：给定字符串输入，断言返回文本），交互式
    读键盘这部分放在这里，只在主循环里被调用——这样"要不要弹交互菜单"这个
    决定权在调用方，纯逻辑和 I/O 分开。
    """
    console.print("[secondary]可选档位：[/secondary]")
    options = [
        (t, f"{t}（{TIER_MODELS[t]}）· {'日常，快' if t == 'sonnet' else '重活，更强'}")
        for t in TIER_MODELS
    ]
    return _prompt_from_list(options, agent.tier, "选择档位序号（回车保持不变）")


def prompt_mode_choice(agent: Agent) -> str:
    """/mode 不带参数时的交互式选择列表，返回选中的权限模式。"""
    console.print("[secondary]可选权限模式：[/secondary]")
    hints = {
        "default": "只读放行，写文件/执行命令都要问",
        "accept-edits": "写文件自动放行，执行命令仍要问",
        "yolo": "全部自动放行，不询问（危险）",
    }
    options = [(m, f"{m} · {hints[m]}") for m in MODES]
    return _prompt_from_list(options, agent.permissions.mode, "选择模式序号（回车保持不变）")


def prompt_plan_choice(agent: Agent) -> str:
    """/plan 不带参数时的交互式选择列表，返回 "on" 或 "off"。"""
    console.print("[secondary]计划模式：[/secondary]")
    options = [
        ("off", "off · 正常模式，agent 可以直接修改"),
        ("on", "on  · 只读调研出方案，不实际修改"),
    ]
    current = "on" if agent.plan_mode else "off"
    return _prompt_from_list(options, current, "选择序号（回车保持不变）")


def prompt_resume_choice() -> Path | None:
    """/resume 的交互式会话选择列表；没有历史会话或用户取消时返回 None。"""
    sessions = session.list_sessions()
    if not sessions:
        console.print("[secondary]没有可恢复的历史会话。[/secondary]")
        return None
    console.print("[secondary]最近的会话（新到旧）：[/secondary]")
    for i, path in enumerate(sessions, start=1):
        console.print(f"  [accent]{i}[/accent]. {path.stem} — {session.preview(path)}")
    choice = Prompt.ask(
        "选择要恢复的会话序号（回车取消）",
        choices=[str(i) for i in range(1, len(sessions) + 1)] + [""],
        default="",
        show_choices=False,
        console=console,
    )
    return sessions[int(choice) - 1] if choice else None


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


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _render_prompt(markup: str) -> str:
    """把带 rich 标记的提示符渲染成可以直接传给 input() 的 ANSI 字符串。

    根源问题：`rich.Console.input()` 自己先把 prompt 文字 print 出来，再调用
    不带参数的 input()。这样一来，一旦 `readline` 被 import 了（我们为 Tab
    补全引入的），它完全不知道屏幕上已经有一段"🐳 (sonnet) > "——它以为当前
    行是从第 0 列开始的空提示符。等它需要重绘时（退格、或者补全候选列表弹出
    之后）就会按错误的列号去清屏/重画，把已经打印好的彩色 prompt 文字也吃掉，
    这正是"往回退格时 (sonnet) 被吞掉"的原因。

    修法：把 prompt 作为参数传给 input()，让 readline 自己管理它的宽度；
    再用 \\001/\\002（readline 的标准约定）包住颜色转义码，告诉它这些字节
    不占可见列数——否则 readline 会把颜色码也当成"可见字符"算进宽度，一样会错位。
    """
    with console.capture() as capture:
        console.print(markup, end="")
    ansi = capture.get()
    if readline is None:
        return ansi  # 没有 readline 就不存在这个问题，原样返回即可
    return _ANSI_ESCAPE_RE.sub(lambda m: f"\001{m.group(0)}\002", ansi)


def _setup_completion() -> None:
    """给 slash 命令（含 skill 名）挂上 Tab 补全：纯标准库 `readline`，不加新依赖。

    这跟 Claude Code 那种"打字过程中自动弹出候选框"不是一回事——那个需要
    `prompt_toolkit`/`textual` 这类接管整个终端渲染的库（跟之前讨论"动态
    变形输入框"是同一个依赖限制）。`readline` 是"按 Tab 触发"的传统 shell
    补全（跟 bash/Python REPL 一样），够用、零新依赖，缺点是不会主动弹出来，
    得自己按一下 Tab。
    """
    if readline is None:  # Windows 没有内置 readline，静默跳过
        return

    def completer(text: str, state: int) -> str | None:
        if not text.startswith("/"):
            return None
        candidates = sorted(set(BUILTIN_COMMANDS) | {f"/{name}" for name in skills.discover_skills()})
        matches = [c for c in candidates if c.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    # "/" 默认在 readline 的分词分隔符里，会把 "/model" 从 "/" 处切开，
    # 补全时只剩 "model" 这个词——去掉它，"/model" 才会被当成一个整体来补全。
    readline.set_completer_delims(readline.get_completer_delims().replace("/", ""))
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")  # macOS 自带的是 libedit 版 readline
    else:
        readline.parse_and_bind("tab: complete")


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
        with Live(
            Spinner("dots", text=f"{MASCOT} {verb}…", style="accent"),
            console=console,
            refresh_per_second=8,
        ) as live:
            def on_text(chunk: str) -> None:
                nonlocal accumulated
                accumulated += chunk
                live.update(Markdown(accumulated))

            reply = agent.run_turn(user_input, on_text=on_text)
            live.update(Markdown(reply if reply else accumulated))
    except KeyboardInterrupt:
        del agent.messages[checkpoint:]
        console.print("\n[warn](已中断，本轮输入已丢弃)[/warn]")
        return
    except Exception as exc:
        del agent.messages[checkpoint:]
        console.print(f"\n[warn]本轮请求失败：{exc}[/warn]")
        return

    used_pct = round(agent.context.last_input_tokens / CONTEXT_WINDOW_TOKENS * 100)
    console.print(
        f"[dim]  context: {agent.context.last_input_tokens} tokens（{used_pct}%）"
        f" · {agent.tier}（{agent.model}）[/dim]"
    )


# 参数字典里挑一个最能代表"在干什么"的字段做单行预览，而不是把整个字典甩
# 出来——这是 Claude Code 里 `⏺ Read(file.py)` 这种简洁风格的关键。
_ARG_PREVIEW_KEYS = ("path", "command", "pattern", "name", "description", "goal")
_ERROR_PREFIXES = ("错误", "工具执行出错", "操作被", "用户拒绝")


def _preview_args(tool_input: dict) -> str:
    for key in _ARG_PREVIEW_KEYS:
        if key in tool_input:
            return str(tool_input[key])[:100]
    return str(tool_input)[:100]


def _print_tool_call(name: str, tool_input: dict) -> None:
    console.print(f"[tool]⏺[/tool] {name}[dim]({_preview_args(tool_input)})[/dim]")


def _print_tool_result(name: str, tool_input: dict, result: str) -> None:
    """工具结果的一行摘要，缩进对齐在调用行下面、带 ⎿ 前缀——对应 Claude
    Code 工具调用后紧跟的那行结果摘要，一眼看出"发生了什么"而不用把完整
    返回值塞进对话流。edit_file 成功时改画彩色 diff，比一句"已修改"有用。
    """
    if name == "edit_file" and result.startswith(("已修改", "已创建新文件")):
        _print_edit_diff(tool_input)
        return
    first_line = result.splitlines()[0] if result else ""
    style = "warn" if first_line.startswith(_ERROR_PREFIXES) else "dim"
    console.print(f"  [{style}]⎿ {first_line[:100]}[/{style}]")


def _print_edit_diff(tool_input: dict) -> None:
    old_str = tool_input.get("old_str", "")
    new_str = tool_input.get("new_str", "")
    diff = difflib.unified_diff(old_str.splitlines(), new_str.splitlines(), lineterm="", n=0)
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"  [green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"  [red]{line}[/red]")


GOAL_DONE_MARK = "<DONE>"
GOAL_MAX_ROUNDS = 30


def run_goal_mode(agent: Agent, goal: str, max_rounds: int = GOAL_MAX_ROUNDS) -> bool:
    """goal 模式（M9f）：给定目标自主循环到完成，不等用户输入。

    机制：第一轮下达目标；之后每轮自动注入"继续"提示，直到模型输出
    完成标记或达到轮数上限。这不是新的循环——只是把"用户说继续"这个
    动作自动化了，复用 run_turn 不动任何核心代码。返回是否完成。
    """
    first = (
        f"目标：{goal}\n"
        f"请自主完成这个目标。全部完成并验证后，在回复末尾单独输出 {GOAL_DONE_MARK}。"
    )
    for round_no in range(1, max_rounds + 1):
        prompt = first if round_no == 1 else (
            f"继续完成目标。如果目标已全部完成并验证，在回复末尾单独输出 {GOAL_DONE_MARK}。"
        )
        console.print(f"[dim]—— goal 模式 第 {round_no} 轮 ——[/dim]")
        reply = agent.run_turn(prompt)
        console.print(Markdown(reply.replace(GOAL_DONE_MARK, "")))
        if GOAL_DONE_MARK in reply:
            console.print("[green]✔ 目标完成[/green]")
            return True
    console.print(f"[yellow]达到 {max_rounds} 轮上限，目标未确认完成[/yellow]")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(prog="minicode")
    parser.add_argument("--tier", default=DEFAULT_TIER, choices=list(TIER_MODELS), help="模型档位")
    parser.add_argument("--base-url", help="Anthropic 兼容端点 URL；默认 DeepSeek")
    parser.add_argument("--model", help="具体模型名；覆盖 --tier 的初始映射")
    parser.add_argument("--mode", default="default", choices=list(MODES), help="权限模式")
    parser.add_argument("--resume", action="store_true", help="恢复最近一次会话")
    parser.add_argument("--session-id", help="恢复指定会话 ID（用于 -p）")
    parser.add_argument("--goal", help="goal 模式：给定目标自主执行到完成（建议配合 --mode accept-edits）")
    parser.add_argument("-p", "--print", dest="prompt", help="非交互运行一轮")
    parser.add_argument("--output-format", choices=("text", "json", "stream-json"), default="text")
    args = parser.parse_args()
    if args.prompt is not None and args.output_format != "text" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = load_settings()
    max_loops = settings.get("max_loops", 40)
    if not isinstance(max_loops, int) or max_loops < 1:
        parser.error("max_loops 必须是正整数")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if args.prompt is not None and not api_key:
        if args.output_format in ("json", "stream-json"):
            print(json.dumps({"type": "error", "error": "缺少 ANTHROPIC_API_KEY"}, ensure_ascii=False))
        else:
            print("缺少 ANTHROPIC_API_KEY", file=sys.stderr)
        raise SystemExit(2)
    if not api_key:
        # 首次体验友好一点：不直接报错退出，而是当场问一次。只留在这个
        # 进程的内存里传给 Agent，不写环境变量、不落盘——CLAUDE.md red line。
        # 想长期免输入，请按 README 把 export 写进自己的 shell 配置文件。
        console.print(
            "[secondary]没有检测到环境变量 ANTHROPIC_API_KEY。[/secondary]\n"
            "[dim]去 DeepSeek 开放平台控制台生成一个 key（sk- 开头）后粘贴进来；"
            "只在这次运行里生效，不会保存到任何文件。[/dim]"
        )
        try:
            api_key = Prompt.ask("API Key", password=True, console=console)
        except (EOFError, KeyboardInterrupt, OSError):
            # OSError：非交互环境（管道、CI、pytest 捕获 stdin 等）读不了键盘，
            # 跟真的按了 Ctrl+D 一样处理——没有 key 就退出，不让进程挂在这里。
            api_key = ""
        if not api_key:
            console.print("[warn]未提供 API Key，退出。[/warn]")
            sys.exit(1)

    # 启动横幅仿 Claude Code：一个圆角边框把"工具名 + 当前状态"框起来，
    # 一眼就知道启动的是 minicode（而不是被淹没在一堆日志里）。
    banner_body = (
        f"[banner]{MASCOT} 欢迎使用 minicode！[/banner]\n\n"
        f"[secondary]档位 {args.tier}（{resolve_model(args.tier)}） · 权限 {args.mode}[/secondary]\n"
        f"[secondary]cwd: {os.getcwd()}[/secondary]\n\n"
        f"[dim]/help 查看命令[/dim]"
    )
    if args.prompt is None:
        console.print(Panel(banner_body, border_style="accent", padding=(1, 2), expand=False))
    if args.mode == "yolo" and args.prompt is None:
        console.print("[warn]⚠ yolo 模式：所有工具调用不经确认直接执行[/warn]")

    # MCP 工具在入口加载一次（而不是在 Agent 里），混入本地工具集；
    # agent 循环对两者一视同仁。
    from minicode.mcp_client import load_mcp_tools
    from minicode.tools import TOOLS

    mcp_tools = load_mcp_tools()
    if mcp_tools and args.prompt is None:
        console.print(f"[dim]已加载 {len(mcp_tools)} 个 MCP 工具：{', '.join(t.name for t in mcp_tools)}[/dim]")

    def emit_event(kind: str, **payload: object) -> None:
        print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)

    agent = Agent(
        api_key=api_key,
        tier=args.tier,
        base_url=args.base_url or settings.get("base_url"),
        model=args.model or settings.get("model"),
        max_loops=max_loops,
        on_tool_call=(lambda name, inp: emit_event("tool_call", name=name, input=inp))
        if args.output_format == "stream-json" and args.prompt is not None else
        (None if args.prompt else _print_tool_call),
        permissions=PermissionManager(mode=args.mode, ask_user=(lambda _n, _i: "n") if args.prompt else None,
                                      rules=settings["permissions"]),
        tools=TOOLS + mcp_tools,
    )
    agent.on_compact = lambda b, a: console.print(f"[dim]  ⚙ 上下文已压缩：{b} -> {a} 条消息[/dim]")
    agent.on_tool_result = (lambda name, inp, result: emit_event("tool_result", name=name, result=result)) \
        if args.output_format == "stream-json" and args.prompt is not None else \
        (None if args.prompt else _print_tool_result)

    if args.prompt is not None:
        try:
            if args.session_id:
                target = (session.SESSION_DIR / f"{args.session_id}.json").resolve()
                if target.parent != session.SESSION_DIR.resolve():
                    raise ValueError("无效会话 ID")
                agent.messages = session.load(target)
            elif args.resume:
                agent.messages = session.load_latest() or []
            reply = agent.run_turn(args.prompt, on_text=(lambda chunk: emit_event("text_delta", text=chunk))
                                   if args.output_format == "stream-json" else None)
            session_path = session.new_session_path()
            session.save(session_path, agent.messages)
            if args.output_format == "json":
                print(json.dumps({"result": reply, "session_id": session_path.stem,
                                  "usage_tokens": agent.context.cumulative_tokens}, ensure_ascii=False))
            elif args.output_format == "stream-json":
                emit_event("result", result=reply, session_id=session_path.stem,
                           usage_tokens=agent.context.cumulative_tokens)
            else:
                print(reply)
        except Exception as exc:
            if args.output_format == "json":
                print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            elif args.output_format == "stream-json":
                emit_event("error", error=str(exc))
            else:
                print(f"运行失败：{exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    if args.goal:
        if args.mode == "default":
            console.print("[dim]提示：goal 模式建议配合 --mode accept-edits，否则每次写操作都会停下等确认[/dim]")
        run_goal_mode(agent, args.goal)
        return

    if args.resume:
        restored = session.load_latest()
        if restored:
            agent.messages = restored
            console.print(f"[dim]已恢复上次会话（{len(restored)} 条消息）[/dim]")
        else:
            console.print("[dim]没有可恢复的会话，从新对话开始[/dim]")

    session_path = session.new_session_path()
    _setup_completion()

    while True:
        try:
            # 提示符里带上当前档位，/model 切换后这里会立刻跟着变，
            # 不用额外去看 /cost 或 banner 才知道现在跑的是哪个模型。
            # 用 _render_prompt 传给 input()（而不是 console.input()），是为了
            # 让 readline 知道这段彩色文字的真实宽度——见 _render_prompt 的注释。
            prompt_str = _render_prompt(f"\n[accent]{MASCOT}[/accent] [secondary]({agent.tier})[/secondary] > ")
            user_input = input(prompt_str).strip()
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
            builtin = set(BUILTIN_COMMANDS)
            # 这几个命令不带参数时不甩一句"用法：..."就完事，而是弹交互式选择列表
            pickers = {"/model": prompt_model_choice, "/mode": prompt_mode_choice, "/plan": prompt_plan_choice}
            if user_input in pickers:
                try:
                    chosen = pickers[user_input](agent)
                except (EOFError, KeyboardInterrupt):
                    console.print("[warn](已取消)[/warn]")
                    continue
                console.print(handle_slash(f"{user_input} {chosen}", agent))
                continue
            if user_input == "/resume":
                try:
                    picked = prompt_resume_choice()
                except (EOFError, KeyboardInterrupt):
                    console.print("[warn](已取消)[/warn]")
                    continue
                if picked is not None:
                    agent.messages = session.load(picked)
                    console.print(f"[secondary]已恢复会话 {picked.stem}（{len(agent.messages)} 条消息）[/secondary]")
                continue
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
