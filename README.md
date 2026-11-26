# mini-code 🐳

## 当前开发版的运行边界

- 模型推理仍通过远程 API；本地 agent 本身可在 CPU 上运行。使用 `--base-url` 和 `--model` 可选择 Anthropic 兼容端点与模型，默认仍是 DeepSeek。
- Linux 上的 shell、文件工具、hooks 和本地 MCP 进程需要安装 `bubblewrap`，且内核必须允许创建用户命名空间；缺少任一条件时拒绝执行。沙箱限制网络并将工作目录作为可写区域。`.github/workflows/linux-sandbox.yml` 已在 Ubuntu 22.04 完成原生端到端验收（127 通过、8 个条件跳过，[运行记录](https://github.com/sy-victoria/my_claude/actions/runs/45793684813)）。Ubuntu 24.04 GitHub runner 的 AppArmor 默认策略曾阻止 `bwrap` 创建网络命名空间，程序因此保持拒绝执行。
- Windows 和 macOS 使用本地 Docker 的 Linux 容器运行 shell、文件工具、hooks 和本地 MCP；需要 Docker Desktop 或兼容的本地 Docker 引擎，以及已缓存的 `python:3.11.11-slim-bookworm` 镜像（可用 `MINICODE_SANDBOX_IMAGE` 指定其他已缓存的 Python 镜像）。容器禁用网络、仅挂载工作区与只读程序包，并限制权限和资源。命令按 Linux `sh` 语法执行。Windows 路径已完成集成测试；`.github/workflows/macos-sandbox.yml` 用 macOS Intel runner + Colima 运行实机验收。
- Windows Docker 集成测试可通过设置 `MINICODE_TEST_DOCKER=1` 后运行 `pytest tests/test_docker_integration.py tests/test_bash.py tests/test_mcp.py`；默认单元测试不启动 Docker。
- `-p "任务" --output-format json` 可运行单轮并返回 JSON；`stream-json` 输出逐行事件。结果包含 `status=complete|incomplete`；达到循环、时间、工具调用或模型输出上限时以非零退出码报告未完成。`--resume` 恢复最近会话，`--session-id ID` 恢复指定会话。非交互运行中需要确认的工具会被拒绝。
- 用户设置为 `~/.minicode/settings.json`，项目设置为 `.minicode/settings.json`。用户可配置 `max_loops`（默认 40）、`api_timeout_seconds`（默认 90）、`max_turn_seconds`（默认 600）、`max_tool_calls`（默认 100），以及 `model` 和 `permissions` 的 `allow`、`ask`、`deny` 规则；例如 `bash:git status`。`bash` 的 allow 规则只接受完整命令精确匹配。项目设置可收紧 `max_loops`，但不能指定其他运行上限、新增 `allow` 规则或指定会接收 API Key 的 `base_url`；该地址只能在用户设置或 CLI 参数中指定。API 失败发生在工具执行后时，会保留完整会话记录供恢复。
- 项目级 `.minicode/mcp.json` 可配置本地 MCP 的 `command`；其沙箱工作目录只读，防止服务启动时直接修改项目。远程 HTTP MCP 必须配置在用户级 `~/.minicode/mcp.json`，使用 `url`。可配置 `token_env` 使用已有 Bearer token，也可配置 `"oauth": {}` 使用浏览器授权；如果服务不支持动态客户端注册，可在 `oauth.client_id` 中提供已注册的公共客户端 ID，`oauth.scope` 可指定所需范围。OAuth 使用 PKCE、受保护资源和授权服务器元数据，令牌只保存在当前进程内存中；非交互运行不能启动浏览器，需使用 `token_env`。工具清单请求失败时会尝试重新握手一次。远程会话过期时会重新握手，写工具不会自动重放，避免重复副作用。

用户级远程 MCP 配置示例：

```json
{"servers": {"docs": {"url": "https://example.com/mcp", "oauth": {}}}}
```

从零复现一个 Claude Code 风格的 coding agent，用于学习 agent 架构。

**核心思想：Agent = LLM + 工具 + 循环。** 本项目用 Python + Anthropic API，分 9 个里程碑逐步复现 Claude Code 的核心架构：agent 循环 → bash 工具 → 权限系统 → 系统提示词与项目记忆 → 搜索/编辑工具箱 → 上下文管理 → 子 Agent → 终端体验。

## 一行命令体验（不用 clone，给同学玩的）

```bash
# 1. 装 uv（已经装过可跳过）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 一行跑起来（把 sk-xxx 换成你自己的 DeepSeek API Key）
ANTHROPIC_API_KEY=sk-xxx uvx --from git+https://github.com/sy-victoria/my_claude minicode
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
git clone https://github.com/sy-victoria/my_claude.git
cd my_claude
export ANTHROPIC_API_KEY=sk-...   # 你的 DeepSeek API Key（走 DeepSeek 的 Anthropic 协议兼容端点）
uv sync
uv run minicode
```

> 模型后端用的是 DeepSeek，但走它的 **Anthropic 协议兼容端点**（`base_url=https://api.deepseek.com/anthropic`），所以代码里仍然用官方 `anthropic` SDK，无需切换 SDK。详见 [CLAUDE.md](CLAUDE.md) 3.2 节。

## 当前状态

原项目的教学里程碑（M0~M9 含 6 个 M9 扩展）已完成；本仓库正在补齐权限、沙箱、远程 MCP 和跨平台验收。Windows 本机单元测试为 118 通过、17 个条件跳过；Linux 原生验收为 127 通过、8 个条件跳过。macOS 沙箱仍待实机验收。

已实现的能力：agent 循环、10 个工具（文件/搜索/bash/子agent/skill/todo）、三档权限系统、系统提示词与 AGENT.md 项目记忆、上下文自动压缩、流式终端（DeepSeek 蓝色主题 + 🐳 吉祥物、交互式菜单、`/resume` 会话恢复、`⏺`/`⎿` 工具调用日志 + 彩色 diff）、skill 系统（渐进式披露）、plan mode、手写 MCP 客户端、goal 无人值守模式、hooks。

学习路径：按编号顺序阅读 `docs/devlog/`（每篇都有"跟着学"代码导读），想自己动手试玩看 `docs/03-testing-guide.md`。
