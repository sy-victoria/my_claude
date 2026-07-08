# mini-code

从零复现一个 Claude Code 风格的 coding agent，用于学习 agent 架构。

**核心思想：Agent = LLM + 工具 + 循环。** 本项目用 Python + Anthropic API，分 9 个里程碑逐步复现 Claude Code 的核心架构：agent 循环 → bash 工具 → 权限系统 → 系统提示词与项目记忆 → 搜索/编辑工具箱 → 上下文管理 → 子 Agent → 终端体验。

## 项目文档导航

| 文件 | 内容 | 谁看 |
|---|---|---|
| [CLAUDE.md](CLAUDE.md) | 执行规范：工作流程、代码规范、红线 | 执行本项目的 AI |
| [docs/00-roadmap.md](docs/00-roadmap.md) | 里程碑清单 + 验收标准（进度唯一权威） | 所有人 |
| [docs/01-architecture.md](docs/01-architecture.md) | 架构解析：Claude Code 怎么工作、我们复现什么 | 学习者必读 ⭐ |
| [docs/02-resources.md](docs/02-resources.md) | 教程与参考项目清单 | 学习者 |
| [docs/devlog/](docs/devlog/) | 每个里程碑的开发日志（含"跟着学"指引） | 学习者 |

## 快速开始（M0 完成后生效）

```bash
export ANTHROPIC_API_KEY=sk-...   # 你的 DeepSeek API Key（走 DeepSeek 的 Anthropic 协议兼容端点）
uv sync
uv run minicode
```

> 模型后端用的是 DeepSeek，但走它的 **Anthropic 协议兼容端点**（`base_url=https://api.deepseek.com/anthropic`），所以代码里仍然用官方 `anthropic` SDK，无需切换 SDK。详见 [CLAUDE.md](CLAUDE.md) 3.2 节。

## 当前状态

尚未开始实现。执行者请读 CLAUDE.md 后从 `docs/00-roadmap.md` 的 M0 开始。
