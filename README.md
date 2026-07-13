# mini-code 🐳

从零复现一个 Claude Code 风格的 coding agent，用于学习 agent 架构。

**核心思想：Agent = LLM + 工具 + 循环。** 本项目用 Python + Anthropic API，分 9 个里程碑逐步复现 Claude Code 的核心架构：agent 循环 → bash 工具 → 权限系统 → 系统提示词与项目记忆 → 搜索/编辑工具箱 → 上下文管理 → 子 Agent → 终端体验。

## 一行命令体验（不用 clone，给同学玩的）

```bash
# 1. 装 uv（已经装过可跳过）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 一行跑起来（把 sk-xxx 换成你自己的 DeepSeek API Key）
ANTHROPIC_API_KEY=sk-xxx uvx --from git+https://github.com/limit-coding/coding-agent minicode
```

没有 DeepSeek Key？去 DeepSeek 开放平台控制台注册、生成一个 `sk-` 开头的 key 就行，跟 OpenAI/Anthropic 那套流程差不多。

没提前设置 `ANTHROPIC_API_KEY` 也没关系，`minicode` 启动时检测不到会当场问你要——**只在这次运行的内存里生效，不会写进任何文件**（这是本项目 [CLAUDE.md](CLAUDE.md) 的红线：Key 绝不落盘）。想以后不用每次都输，把它写进自己的 shell 配置：

```bash
echo 'export ANTHROPIC_API_KEY=sk-xxx' >> ~/.zshrc && source ~/.zshrc
```

`uvx --from git+...` 每次都会拉最新代码跑在一个临时环境里，不占用你机器上的目录，退出后不留痕迹（除了 `~/.minicode/` 下的会话记录，见下文 `/resume`）。

## 项目文档导航

| 文件 | 内容 | 谁看 |
|---|---|---|
| [CLAUDE.md](CLAUDE.md) | 执行规范：工作流程、代码规范、红线 | 执行本项目的 AI |
| [docs/00-roadmap.md](docs/00-roadmap.md) | 里程碑清单 + 验收标准（进度唯一权威） | 所有人 |
| [docs/01-architecture.md](docs/01-architecture.md) | 架构解析：Claude Code 怎么工作、我们复现什么 | 学习者必读 ⭐ |
| [docs/02-resources.md](docs/02-resources.md) | 教程与参考项目清单 | 学习者 |
| [docs/03-testing-guide.md](docs/03-testing-guide.md) | 个人测试指南：怎么亲手试玩每个里程碑 | 想动手的人 |
| [docs/04-terminal-ux.md](docs/04-terminal-ux.md) | 终端 UI / slash 命令怎么做的（M9 之后的打磨） | 学习者 |
| [docs/devlog/](docs/devlog/) | 每个里程碑的开发日志（含"跟着学"指引） | 学习者 |

## 本地开发（要改代码用这个）

```bash
git clone https://github.com/limit-coding/coding-agent.git
cd coding-agent
export ANTHROPIC_API_KEY=sk-...   # 你的 DeepSeek API Key（走 DeepSeek 的 Anthropic 协议兼容端点）
uv sync
uv run minicode
```

> 模型后端用的是 DeepSeek，但走它的 **Anthropic 协议兼容端点**（`base_url=https://api.deepseek.com/anthropic`），所以代码里仍然用官方 `anthropic` SDK，无需切换 SDK。详见 [CLAUDE.md](CLAUDE.md) 3.2 节。

## 当前状态

**全部 10 个里程碑（M0~M9 含 6 个 M9 扩展）已完成**，100 个测试全绿，每个里程碑都经过真实 API 验收。

已实现的能力：agent 循环、10 个工具（文件/搜索/bash/子agent/skill/todo）、三档权限系统、系统提示词与 AGENT.md 项目记忆、上下文自动压缩、流式终端（DeepSeek 蓝色主题 + 🐳 吉祥物、交互式菜单、`/resume` 会话恢复、`⏺`/`⎿` 工具调用日志 + 彩色 diff）、skill 系统（渐进式披露）、plan mode、手写 MCP 客户端、goal 无人值守模式、hooks。

学习路径：按编号顺序阅读 `docs/devlog/`（每篇都有"跟着学"代码导读），想自己动手试玩看 `docs/03-testing-guide.md`。
