"""上下文（token 预算）管理，将在 M6 实现。

设计思想（详见 docs/00-roadmap.md M6 与 docs/01-architecture.md 3.3 节）：
上下文窗口是稀缺资源。这里负责 token 用量跟踪，以及接近窗口上限时的
compaction（用一次额外的模型调用把旧对话压缩成摘要，替换掉旧消息）。
"""
