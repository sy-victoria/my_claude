"""minicode：一个从零复现的 Claude Code 风格 coding agent，用于学习 agent 架构。

包结构导览（详见 docs/01-architecture.md）：
    config.py       模型/常量配置
    agent.py        核心 agent 循环（全项目最重要的文件，M1 实现）
    tools/          工具实现，每个工具对应模型可调用的一个能力
    permissions.py  工具执行前的统一权限守门人（M3 实现）
    context.py      token 用量跟踪与上下文压缩（M6 实现）
    cli.py          终端交互入口
"""
