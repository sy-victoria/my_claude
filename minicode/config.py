"""集中存放模型、常量与配置。

模型后端说明：我们用的是 DeepSeek 的 **Anthropic 协议兼容端点**，代码里仍然用官方
`anthropic` SDK 调用，唯一的区别是把 `base_url` 指向 DeepSeek，认证同样走
`x-api-key` header（SDK 默认行为，无需改调用方式）。

已知限制（相对官方 Anthropic API）：
    - 不支持图片 / 文档类型的消息内容
    - `cache_control`、`anthropic-beta`、`top_k` 等高级字段会被静默忽略
    - `thinking` 支持开启，但 `budget_tokens` 字段被忽略
    - 不支持 MCP 工具（M9d 我们自己手写 MCP 客户端，把远程工具转换成普通工具
      混入本地工具注册表，不依赖 DeepSeek 端的 MCP 支持，因此不受此限制影响）
"""

BASE_URL = "https://api.deepseek.com/anthropic"

# 档位映射：DeepSeek 官方按算力/价格把自家模型映射到 Claude 的档位体系。
# 我们不在业务代码里直接写死具体模型名字符串，而是统一通过 resolve_model()
# 查表——这样以后要换模型/换供应商，只需要改这一处。
TIER_MODELS: dict[str, str] = {
    "sonnet": "deepseek-v4-flash",  # 日常档位：快、便宜，默认用这个
    "opus": "deepseek-v4-pro",  # 重活档位：更强但更慢/更贵，按需切换
}

DEFAULT_TIER = "sonnet"

MAX_TOKENS = 8192

# bash 工具的安全参数（CLAUDE.md 第五节）：超时保护进程，截断保护上下文窗口。
BASH_TIMEOUT_SECONDS = 30
BASH_MAX_OUTPUT_CHARS = 2000


def resolve_model(tier: str) -> str:
    """把档位名（"sonnet" / "opus"）解析成具体的模型名。

    档位名而非具体模型名是暴露给 CLI 参数（--tier）和运行时命令（/model）的
    唯一接口，业务代码不应该在别处直接引用 TIER_MODELS。
    """
    if tier not in TIER_MODELS:
        valid = ", ".join(TIER_MODELS)
        raise ValueError(f"未知档位 {tier!r}，可选：{valid}")
    return TIER_MODELS[tier]
