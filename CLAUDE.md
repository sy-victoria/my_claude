# CLAUDE.md — 本项目的执行规范

> 本文件是给执行本项目的 AI（以及人类协作者）的行为规范。**每次开始工作前必须先读完本文件。**

## 一、项目是什么

本项目名为 **mini-code**：从零复现一个 Claude Code 风格的 coding agent（终端里的 AI 编程助手），目的是**学习 agent 架构**，而不是造一个生产级产品。

- 技术栈：**Python 3.10+ + Anthropic API**（官方 `anthropic` SDK）
- 项目所有者是一位 agent 架构的初学者，本项目的第一产出是**可读的代码和文档**，第二产出才是能跑的工具
- 核心思想（必须贯穿始终）：**agent = LLM + 工具 + 循环**。消息列表（message list）是唯一的状态，没有复杂的状态机

## 二、工作流程（最重要的一节）

### 2.1 严格按里程碑推进

1. 开始前，读 `docs/00-roadmap.md`，找到**第一个未完成**的里程碑（M0 → M9 顺序推进）
2. 再读 `docs/devlog/` 下**最新一篇**开发日志，了解上次做到哪、有什么遗留问题
3. **一次只做一个里程碑**。禁止跳过、禁止合并多个里程碑、禁止"顺手"实现后面里程碑的功能
4. 实现完成后，必须逐条核对该里程碑的"验收标准"，**实际运行验证**（不是只看代码），全部通过才算完成

### 2.2 每个里程碑完成后必须做的三件事

1. **写开发日志**：在 `docs/devlog/` 新建 `NN-milestone-名称.md`（按模板 `docs/devlog/README.md`），用中文写清楚：做了什么、关键设计决策及理由、踩了什么坑、验收结果
2. **更新 roadmap**：把 `docs/00-roadmap.md` 里对应里程碑的复选框勾上（`[ ]` → `[x]`）
3. **Git 提交**：一个里程碑一个 commit，格式 `M<编号>: <一句话说明>`，例如 `M1: 最小 agent 循环 + 三个文件工具`

### 2.3 遇到问题时

- 验收标准无法通过 → 不要绕过或删改验收标准，修到通过为止；确实修不动就在 devlog 里如实记录，停下来等项目所有者决定
- 发现 roadmap 设计有问题 → 不要擅自改架构，在 devlog 里提出建议，等项目所有者确认

## 三、代码规范

### 3.1 教学优先（本项目的第一原则）

- **代码是写给初学者读的**。两种写法之间，永远选更直白的那种，哪怕多几行
- 每个 `.py` 文件顶部必须有模块级 docstring，用中文说明：这个文件在整个架构里扮演什么角色、为什么需要它
- 关键函数写中文 docstring；注释解释"**为什么这么做**"（设计意图、Claude Code 的对应做法），不解释"这行在干什么"
- 不设硬性行数上限；判断要不要拆分文件看职责是否已经混杂，而不是数行数（2026-07-13 项目所有者确认取消原先"~300 行"的规定，理由：行数本身不是好的复杂度信号，机械拆分反而会打散本该放在一起读的逻辑）

### 3.2 技术约束

- **禁止使用任何 agent 框架**（LangChain、LlamaIndex、CrewAI 等）。允许的第三方依赖仅限：`anthropic`（必须）、`rich`（终端渲染，M8 起）、`pytest`（测试）。想加别的依赖，先在 devlog 里说明理由并停下来等确认
- 全部函数带类型标注（type hints）
- 用 `uv` 管理项目（`uv init` / `uv add` / `uv run`）
- **模型后端：走 DeepSeek 的 Anthropic 协议兼容端点**，仍然用官方 `anthropic` SDK，只是把 `base_url` 指向 DeepSeek：
  - `base_url = "https://api.deepseek.com/anthropic"`
  - 认证仍用 `x-api-key` header（SDK 默认行为，`Anthropic(api_key=..., base_url=...)` 两个参数都传即可，不用改 SDK 调用方式）
  - API Key 只从环境变量 `ANTHROPIC_API_KEY` 读取（值是 DeepSeek 控制台发的 key），**任何情况下不得写进代码或配置文件**
  - 模型名用**档位映射**集中定义在 `minicode/config.py`：`TIER_MODELS = {"sonnet": "deepseek-v4-flash", "opus": "deepseek-v4-pro"}`，默认档位 `"sonnet"`（日常用，快）；`"opus"` 档位是重活（复杂重构、子 Agent 里的高难度任务）可切换的更强模型。启动参数 `--tier` 和运行时 `/model` 命令（M8）均基于这个映射，不直接暴露具体模型名字符串
  - **已知限制**（写在 `config.py` 顶部注释里，避免后面里程碑踩坑）：不支持图片/文档类型内容；`cache_control`、`anthropic-beta`、`top_k` 等高级字段会被忽略；`thinking` 的 `budget_tokens` 被忽略；**MCP 工具不支持**（M9d 做的是我们自己手写的 MCP 客户端，把远程工具转成普通工具混入注册表，不依赖 DeepSeek 端的 MCP 支持，所以不受此限制影响，但要在 M9d 的 devlog 里说明这一点）

### 3.3 目录结构约定

```
coding-agent/
├── CLAUDE.md            # 本文件
├── README.md            # 项目介绍 + 快速开始
├── pyproject.toml
├── minicode/            # 源代码包
│   ├── __init__.py
│   ├── config.py        # 模型名、常量、配置
│   ├── agent.py         # 核心 agent 循环（全项目最重要的文件）
│   ├── tools/           # 工具实现，一个工具一个文件
│   │   ├── __init__.py  # 工具注册表（TOOLS 列表）
│   │   ├── base.py      # 工具基类 / 协议定义
│   │   └── ...
│   ├── permissions.py   # 权限系统（M3）
│   ├── context.py       # 上下文管理（M6）
│   └── cli.py           # 入口 / 终端交互
├── tests/               # pytest 测试
└── docs/
    ├── 00-roadmap.md    # 里程碑清单（进度的唯一权威来源）
    ├── 01-architecture.md
    ├── 02-resources.md
    └── devlog/          # 开发日志，NN 递增编号
```

### 3.4 测试

- 每个工具至少一个 pytest 测试（不调 API 的纯逻辑测试：输入 → 工具执行 → 输出断言）
- agent 循环用 mock 的 API 响应测试（不要在测试里真调 Anthropic API 烧钱）
- 提交前 `uv run pytest` 必须全绿

## 四、文档规范

- 所有面向项目所有者的文档（devlog、roadmap、README）用**中文**写；代码标识符、commit message 的技术部分用英文
- devlog 是学习材料，不是流水账：重点写"**为什么**这样设计、Claude Code 是怎么做的、我们简化了什么"
- 每个里程碑的 devlog 里要有一节「**跟着学**」：给初学者列 2~3 个建议阅读的代码位置（`文件:行号`）和阅读顺序

## 五、安全规范

- bash 执行工具（M2 起）必须有：超时（默认 30s）、输出截断（默认 2000 字符）、危险命令黑名单（`rm -rf /`、`sudo` 等直接拒绝）
- M3 权限系统落地前，bash 工具每次执行前都要在终端向用户确认（y/n）
- agent 的文件写入范围限制在当前工作目录内（拒绝绝对路径逃逸和 `..` 逃逸）

## 六、禁止事项（红线）

1. ❌ 跳过或合并里程碑
2. ❌ 引入 agent 框架或未经确认的依赖
3. ❌ 完成里程碑却不写 devlog、不更新 roadmap
4. ❌ 未实际运行验证就声称验收通过
5. ❌ 把 API Key 写进任何文件
6. ❌ 为了"看起来高级"引入抽象（工厂、依赖注入容器、元类等）——这个项目里直白就是高级
