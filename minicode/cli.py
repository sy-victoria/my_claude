"""终端交互入口：一个最小的 REPL，读用户输入、驱动 agent 循环、打印结果。

M1 阶段刻意做得很朴素（没有权限确认、没有流式输出、没有 markdown 渲染，
这些分别是 M3/M8 的内容），只把"人和 agent 怎么对话"这条主干跑通。
"""

import argparse
import os
import sys
from typing import Any

from minicode.agent import Agent
from minicode.config import DEFAULT_TIER
from minicode.permissions import MODES, PermissionManager

WELCOME = f"""\
minicode —— 从零复现的 Claude Code 风格 coding agent（学习项目）

当前档位：{DEFAULT_TIER}（用 --tier sonnet|opus 切换）
输入你的需求开始对话，输入 exit 或 Ctrl+D 退出。\
"""


def _print_tool_call(name: str, tool_input: dict[str, Any]) -> None:
    print(f"  > tool: {name}({tool_input})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="minicode")
    parser.add_argument(
        "--tier", default=DEFAULT_TIER, choices=["sonnet", "opus"], help="模型档位"
    )
    parser.add_argument(
        "--mode", default="default", choices=list(MODES), help="权限模式"
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误：请先设置环境变量 ANTHROPIC_API_KEY")
        sys.exit(1)

    print(WELCOME)
    if args.mode == "yolo":
        print("⚠️  yolo 模式：所有工具调用都会不经确认直接执行，请确认你在安全的目录里。")

    agent = Agent(
        api_key=api_key,
        tier=args.tier,
        on_tool_call=_print_tool_call,
        permissions=PermissionManager(mode=args.mode),
    )

    while True:
        try:
            user_input = input("\n> ").strip()
        except EOFError:
            print()
            break

        if user_input in ("exit", "quit"):
            break
        if not user_input:
            continue

        reply = agent.run_turn(user_input)
        print(reply)


if __name__ == "__main__":
    main()
