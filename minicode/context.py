"""上下文（token 预算）管理：用量跟踪 + compaction 压缩。

上下文窗口是 coding agent 最稀缺的资源。本模块的两个职责：

1. **跟踪**：API 每次响应都带 usage 字段（本次请求的输入+输出 token 数），
   其中输入 token 数 ≈ 当前对话历史的体积，这就是"上下文用了多少"的来源
   ——不需要自己数 token，官方计数是免费送的。

2. **compaction**：接近窗口上限时，用一次额外的模型调用把旧对话总结成
   摘要替换掉。摘要该保留什么、丢什么（见 SUMMARY_INSTRUCTION）是压缩
   质量的关键：保留任务目标/已做决定/文件清单，丢弃工具的原始输出——
   文件内容真需要时 agent 可以重新读，文件系统本身就是外部记忆，这是
   coding agent 独有的优势。
"""

from typing import Any

from minicode import config

# 总结指令：结构模仿 Claude Code compaction prompt 的骨架（它的完整版有
# 几十行，分更多小节）。要求模型保留"能让工作继续下去"的信息。
SUMMARY_INSTRUCTION = """\
请把以上对话历史总结成一段摘要，用于替换原始对话继续工作。必须保留：
1. 用户的任务目标（最初要求做什么、后来有什么变化）
2. 已经做出的关键决定和结论
3. 涉及的文件清单（路径 + 每个文件做了什么改动）
4. 当前进行到哪一步、下一步计划
不要保留：工具返回的原始文件内容、命令输出（需要时可以重新获取）。
直接输出摘要内容，不要加"好的"之类的开场白。"""


class ContextTracker:
    """记录 token 用量。last_input_tokens 近似等于当前上下文体积。"""

    def __init__(self) -> None:
        self.last_input_tokens = 0
        self.cumulative_tokens = 0  # 会话累计（供 /cost 显示）

    def record(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        # 踩坑记录（M6 验收时发现）：启用了 prompt 缓存的后端（DeepSeek 的
        # 兼容端点默认开启）会把命中缓存的输入 token 从 input_tokens 里拆出
        # 去，单独报在 cache_read_input_tokens 里。"当前上下文体积"必须把
        # 三者加总，否则长对话里 input_tokens 会越来越小，compaction 永远
        # 不触发。
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        self.last_input_tokens = input_tokens + cache_read + cache_creation
        self.cumulative_tokens += input_tokens + cache_read + cache_creation + output_tokens

    def should_compact(self) -> bool:
        return self.last_input_tokens >= config.CONTEXT_WINDOW_TOKENS * config.COMPACT_THRESHOLD


def split_for_compaction(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """把 messages 切成（待压缩的旧历史, 保留原文的最近部分）。

    切分点选**最后一条真实用户输入**（content 是字符串的 user 消息；
    tool_result 的 content 是列表，天然被排除）。从真实用户输入处切，
    保证不会把 tool_use / tool_result 对从中间拆开——这两者必须成对出现，
    拆开会导致 API 报错。
    """
    last_user_idx = 0
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg["content"], str):
            last_user_idx = i
    return messages[:last_user_idx], messages[last_user_idx:]


def merge_summary(summary: str, recent: list[dict]) -> list[dict]:
    """把摘要并入保留的消息，维持 user/assistant 交替的合法结构。

    摘要作为前缀合并进 recent 的第一条用户消息，而不是单独插一条——
    避免出现两条相邻的 user 消息（部分 API 实现要求角色严格交替）。
    """
    prefix = f"[之前对话的摘要]\n{summary}\n[摘要结束，以下是最近的对话]\n\n"
    first = recent[0]
    merged = {"role": "user", "content": prefix + first["content"]}
    return [merged, *recent[1:]]
