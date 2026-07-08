"""终端交互入口。

M0 阶段只有一个欢迎语占位；真正的 REPL（读用户输入、驱动 agent 循环、
打印工具调用日志）从 M1 开始逐步搭建。
"""

from minicode.config import DEFAULT_TIER

WELCOME = f"""\
minicode —— 从零复现的 Claude Code 风格 coding agent（学习项目）

当前档位：{DEFAULT_TIER}
提示：请先设置环境变量 ANTHROPIC_API_KEY（DeepSeek 控制台申请的 key）
（M0 阶段尚未接入模型对话，完整功能见 docs/00-roadmap.md 后续里程碑）\
"""


def main() -> None:
    print(WELCOME)


if __name__ == "__main__":
    main()
