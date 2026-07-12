# Roadmap — mini-code 里程碑清单

> 本文件是项目进度的**唯一权威来源**。执行者每次开工先看这里，找到第一个未勾选的里程碑开始做。
> 每个里程碑 = 目标 + 实现清单 + 验收标准 + 学习要点。验收标准必须**实际运行**逐条验证。

## 总路线图

| 里程碑 | 内容 | 对应 Claude Code 的什么 |
|---|---|---|
| M0 | 项目骨架 | — |
| M1 | 最小 agent 循环 + 3 个文件工具 | 核心 agent loop |
| M2 | Bash 工具 | Bash tool |
| M3 | 权限系统 | permission modes / 工具审批 |
| M4 | 系统提示词 + 项目记忆 | system prompt / CLAUDE.md 机制 |
| M5 | 搜索与精确编辑工具 | Glob / Grep / Edit / Write |
| M6 | 上下文管理 | token 预算 / 输出截断 / compaction |
| M7 | 子 Agent | Task tool (sub-agent) |
| M8 | 终端体验 | 流式输出 / slash 命令 / 会话保存 |
| M9（可选） | 扩展方向 | skill / MCP / plan mode / hooks / goal 模式 |

---

## M0 — 项目骨架

- [x] 已完成

**目标**：能 `uv run minicode` 打出一行欢迎语的空壳项目。

**实现清单**：
1. `uv init`，Python >= 3.10，包名 `minicode`
2. `uv add anthropic`，`uv add --dev pytest`
3. 按 CLAUDE.md 3.3 节建立目录结构（空文件 + 模块 docstring 占位）
4. `minicode/config.py`：定义
   - `BASE_URL = "https://api.deepseek.com/anthropic"`（顶部注释写明：走 DeepSeek 的 Anthropic 协议兼容端点，仍用 `anthropic` 官方 SDK，仅 `base_url` 不同；已知限制见 CLAUDE.md 3.2）
   - `TIER_MODELS = {"sonnet": "deepseek-v4-flash", "opus": "deepseek-v4-pro"}`、`DEFAULT_TIER = "sonnet"`
   - `resolve_model(tier: str) -> str`：查表，非法档位报清晰错误
   - `MAX_TOKENS = 8192`
5. `minicode/cli.py`：`main()` 打印欢迎语；`pyproject.toml` 里配置 `[project.scripts] minicode = "minicode.cli:main"`
6. `.gitignore`（`.venv/`、`__pycache__/`、`.env`）；`git init` + 首次提交
7. `README.md`：项目一句话介绍、快速开始（安装、设置 `ANTHROPIC_API_KEY`、运行）

**验收标准**：
- `uv run minicode` 输出欢迎语，退出码 0
- `uv run pytest` 能运行（0 个测试也算通过）
- `git log` 有规范的首次提交

---

## M1 — 最小 agent 循环 + 3 个文件工具 ⭐ 全项目最重要的里程碑

- [x] 已完成

**目标**：复现 Thorsten Ball《How to Build an Agent》：一个能对话、能自主读文件/列目录/改文件的 agent，总代码量控制在 ~400 行内。做完这个里程碑，agent 的本质就懂了。

**实现清单**：
1. `minicode/tools/base.py`：定义工具协议。每个工具 = `name` + `description` + `input_schema`（JSON Schema，给 LLM 看）+ `run(input: dict) -> str`（本地执行）。**description 是给模型的说明书，要认真写**——这是 prompt engineering 的一部分
2. 三个工具（各一个文件）：
   - `read_file(path)`：读文件，带行号返回（`1\t内容` 格式，模仿 Claude Code 的 Read）
   - `list_files(path=".")`：列目录（目录名后加 `/`）
   - `edit_file(path, old_str, new_str)`：把文件中的 `old_str` 精确替换为 `new_str`；`old_str` 为空且文件不存在时=创建新文件。`old_str` 必须唯一匹配，匹配不到或匹配多处要返回**对模型有指导意义的错误信息**（错误信息也是 prompt！）
3. `minicode/tools/__init__.py`：`TOOLS: list` 工具注册表 + `get_tool(name)` 查找
4. `minicode/agent.py`：核心循环 `Agent.run_turn(user_input)`：
   ```
   messages.append(用户输入)
   loop:
       response = client.messages.create(model, messages, tools=工具schema列表)
       messages.append(response 的 assistant 内容块)
       if response.stop_reason != "tool_use":
           return  # 模型说完了，把话筒还给用户
       for 每个 tool_use 块:
           result = 执行对应工具（异常要捕获，错误文本作为 result 返回给模型）
           messages.append(role=user 的 tool_result 块)
       # 继续 loop，把工具结果喂回模型
   ```
   关键点：**`messages` 列表是唯一的状态**；工具报错不 crash，把错误信息返回给模型让它自己纠正
5. `minicode/cli.py`：REPL——读用户输入 → `agent.run_turn()` → 打印模型文本和工具调用日志（`> tool: read_file({"path": ...})` 这种格式），`Ctrl+D`/`exit` 退出；启动参数 `--tier sonnet|opus`（默认 sonnet，见 `config.resolve_model`），决定本次会话用 flash 还是 pro
6. 测试：三个工具的纯逻辑测试 + agent 循环的 mock 测试（伪造一次 tool_use 响应 + 一次文本响应，断言工具被执行、消息序列正确）

**验收标准**（在一个临时测试目录里实际对话验证）：
- 问「这个目录里有什么文件」→ agent 自主调用 `list_files` 并总结
- 问「读一下 xxx 文件并解释」→ 自主调用 `read_file`
- 说「把 xxx 文件里的 A 改成 B」→ 自主调用 `edit_file`，文件真的被改对
- 说「创建一个 fizzbuzz.py 并运行给我看」→ 能创建文件（运行会失败，因为还没有 bash 工具——这正好引出 M2）
- 一次用户输入触发**连续多次**工具调用（如「读所有 py 文件并总结」）时循环工作正常
- `uv run pytest` 全绿

**学习要点**（devlog 里要展开讲）：
- 为什么说 agent 只是「LLM + 循环 + 工具」；`stop_reason` 如何驱动循环
- tool description 和错误信息为什么本质上都是 prompt
- 对照阅读：https://ampcode.com/notes/how-to-build-an-agent

---

## M2 — Bash 工具

- [x] 已完成

**目标**：agent 能执行 shell 命令，从「能改文件」升级为「能干活」（跑测试、装依赖、git 操作）。

**实现清单**：
1. `minicode/tools/bash.py`：`bash(command)` 工具，用 `subprocess.run(..., shell=True, capture_output=True, timeout=30)`
   - 返回 stdout + stderr + exit code（非零退出码要明确告诉模型）
   - 输出超过 2000 字符截断，截断处注明 `[... 截断，共 N 字符]`
   - 超时要捕获 `TimeoutExpired`，返回可读错误
2. 安全（CLAUDE.md 第五节）：危险命令黑名单（`rm -rf /`、`sudo`、`shutdown` 等）直接拒绝并告知模型原因；每次执行前终端打印命令并请用户 y/n 确认（M3 会把这个升级成正式权限系统）
3. 更新 M1 工具的 description，告诉模型现在有 bash 可用
4. 测试：正常命令、非零退出、超时、截断、黑名单各一个用例

**验收标准**：
- 「创建 fizzbuzz.py 并运行给我看」全流程成功（M1 那个失败用例现在通过）
- 「跑一下这个项目的测试」→ agent 会自己 `uv run pytest`
- 用户在确认环节输入 n 时，agent 收到「用户拒绝」并礼貌处理，不 crash
- 让模型执行 `sleep 60` → 30s 超时且有可读报错

**学习要点**：为什么 bash 一个工具就让能力发生质变（组合爆炸）；为什么必须有超时和截断（保护上下文窗口和进程）。

---

## M3 — 权限系统

- [x] 已完成

**目标**：复现 Claude Code 的权限模型雏形：工具执行前经过一个统一的「守门人」，而不是每个工具自己实现确认逻辑。

**实现清单**：
1. `minicode/permissions.py`：
   - 三种模式：`default`（写操作和 bash 要确认，只读放行）、`accept-edits`（文件编辑自动放行，bash 仍确认）、`yolo`（全放行，启动时警告）
   - 每个工具声明自己的 `permission_level: "read" | "write" | "execute"`
   - `check(tool, input) -> allow | ask | deny`；`ask` 时终端提供选项：`y`（本次允许）/ `a`（本会话该工具始终允许）/ `n`（拒绝，拒绝理由会作为 tool_result 返回给模型）
   - 会话级白名单（`a` 选项的记忆）
2. `agent.py` 的工具执行处改为统一走 `permissions.check()`，删掉 M2 里 bash 自带的确认逻辑
3. CLI 加启动参数 `--mode default|accept-edits|yolo`
4. 测试：三种模式 × 三种 level 的决策矩阵

**验收标准**：
- default 模式下 `read_file` 不询问、`edit_file` 和 `bash` 询问
- 按 `a` 之后同一会话内该工具不再询问
- 拒绝后模型能收到拒绝理由并调整做法（实际对话验证一次）

**学习要点**：权限为什么做成独立一层（策略与机制分离）；Claude Code 的 permission modes 与 allowlist 设计。

---

## M4 — 系统提示词 + 项目记忆

- [x] 已完成

**目标**：agent 有正式的 system prompt，并且像 Claude Code 读 CLAUDE.md 一样，启动时自动加载项目的记忆文件。

**实现清单**：
1. `minicode/prompts.py`：系统提示词，包含——身份与职责、工作风格（简洁、先搜索再回答、改完代码要验证）、工具使用规范（何时该用什么工具）、安全约束。**用中文注释逐段解释每段提示词的设计意图**
2. 环境上下文注入：把 cwd、平台、日期、目录一级结构拼进 system prompt（模仿 Claude Code 的 env 区块）
3. 项目记忆：启动时查找 cwd 的 `AGENT.md`（我们自己的「CLAUDE.md 机制」），存在则整体注入 system prompt
4. system prompt 用 SDK 的 `system` 参数传，不占 messages
5. 测试：记忆文件存在/不存在两种情况的 prompt 组装

**验收标准**：
- 在测试项目里放一个 `AGENT.md` 写「回答我时永远先说『收到老板』」→ agent 行为真的改变
- 问「今天几号、我在哪个目录」→ 不调工具直接答对（证明环境注入生效）
- 对比实验记进 devlog：同一个任务，有/无 system prompt 的行为差异

**学习要点**：system prompt 是 agent 的「性格与操作手册」；分层记忆（系统 < 项目 < 会话）的设计。

---

## M5 — 搜索与精确编辑工具

- [x] 已完成

**目标**：补齐在真实代码库里干活所需的工具箱，向 Claude Code 的工具集看齐。

**实现清单**：
1. `glob(pattern)`：按模式找文件（`**/*.py`），按修改时间排序，用 `pathlib` 实现
2. `grep(pattern, path, glob=None)`：正则搜文件内容，返回 `文件:行号:内容`；限制返回条数
3. `write_file(path, content)`：整文件写入（区别于 edit 的局部替换）
4. 强化 `edit_file`：要求编辑前必须先 `read_file`（agent 端记录已读文件集合，未读就编辑则返回错误提示模型先去读——这是 Claude Code 的真实约束，防止模型凭想象改文件）
5. 每个工具的 description 里写清楚「什么时候用我、什么时候用别的工具」（如：找文件名用 glob、找内容用 grep、看内容用 read）
6. 测试补齐

**验收标准**：
- 在一个 ≥20 文件的真实项目里：「找到定义 XXX 函数的文件并重命名这个函数（所有引用一起改）」→ agent 走 grep → read → edit 的正确流程完成
- 未读文件直接 edit 会被拒绝并纠正（构造对话验证）

**学习要点**：工具箱的「正交性」设计；工具 description 如何引导模型选对工具。

---

## M6 — 上下文管理

- [x] 已完成

**目标**：解决长对话的核心工程问题——上下文窗口是稀缺资源。

**实现清单**：
1. `minicode/context.py`：
   - 用 API 返回的 `usage` 字段跟踪 token 消耗，CLI 里显示当前用量
   - 工具结果统一截断策略（大文件读取分页：`read_file` 加 `offset/limit` 参数）
   - **compaction（压缩）**：token 用量超过阈值（如模型上限的 70%）时，用一次额外的 API 调用把历史对话总结成一段摘要，替换旧消息，保留最近几轮原文。触发时在终端提示用户
2. `/compact` 手动触发压缩（slash 命令雏形）
3. 测试：mock 长对话触发 compaction，断言消息被替换且摘要在场

**验收标准**：
- 连续让 agent 读多个大文件把上下文推高 → 自动 compaction 触发，对话还能继续且 agent 记得早期任务目标（在摘要里）
- CLI 能实时看到 token 用量

**学习要点**：为什么 compaction 是 coding agent 从 demo 到可用的分水岭；摘要该保留什么（任务目标、已做决定、文件清单）丢什么（工具原始输出）。

---

## M7 — 子 Agent

- [x] 已完成

**目标**：复现 Task tool：主 agent 可以把「搜索型/探索型」任务派给一个独立上下文的子 agent，只拿回结论，保护主上下文。

**实现清单**：
1. `minicode/tools/task.py`：`task(description, prompt)` 工具。执行时**新建一个 Agent 实例**（全新的空 messages），给它只读工具集（read/list/glob/grep），跑完整的 agent 循环直到产出最终文本，把最终文本作为 tool_result 返回主 agent
2. 约束：子 agent 不能再派生子 agent（工具集里不含 task）——防递归；子 agent 最大循环次数限制（如 15 轮）
3. CLI 里子 agent 的工具调用日志加缩进/前缀区分显示
4. 测试：mock 验证子 agent 独立消息列表、工具集受限

**验收标准**：
- 「这个项目哪里处理了权限检查？帮我全面调查」→ 主 agent 派 task，子 agent 搜完返回总结，主 agent 的 messages 里只多了一条结论（打印消息数验证上下文被保护）
- 子 agent 内无法调用 task（构造验证）

**学习要点**：子 agent 的本质=用 API 花费换上下文空间；为什么 Claude Code 的 sub-agent 禁止递归。

---

## M8 — 终端体验

- [x] 已完成

**目标**：从能用到好用，向 Claude Code 的交互体验看齐。

**实现清单**：
1. `uv add rich`：markdown 渲染模型回复、工具调用彩色显示、spinner
   - spinner 配随机趣味状态词（复现 Claude Code 彩蛋）：维护一个动名词词表（Musing…、Pondering…、Brewing…、Scheming…、Noodling… 等 20+ 个），每次等待模型时随机选一个显示
2. 流式输出：`client.messages.stream(...)`，文本边生成边打印
3. slash 命令：`/help`、`/clear`（清空 messages）、`/compact`、`/cost`（token 用量）、`/mode`（切权限模式）、`/model sonnet|opus`（运行时切档位，走 `config.resolve_model`，改的是下一次请求用的模型，不影响已有 messages）
4. 会话持久化：messages 序列化到 `~/.minicode/sessions/`，`--resume` 恢复最近会话
5. 中断处理：`Ctrl+C` 打断当前生成回到输入提示符，而不是退出程序

**验收标准**：
- 流式输出肉眼可见；markdown 代码块有高亮
- 每个 slash 命令实测可用
- 退出后 `--resume` 能接着上次对话继续
- 生成途中 `Ctrl+C` 不退出程序

**学习要点**：REPL 状态管理；流式 API 与 tool use 的配合。

---

## M9 — 扩展方向（可选，每个都是独立小里程碑，推荐顺序 e → b → d → a → f → c）

### M9e — Skill 系统（复现 Claude Code 的 Agent Skills / 斜杠命令）

- [x] 已完成

**实现清单**：
1. skill 的形态：一个目录一个 skill，目录内 `SKILL.md` = YAML frontmatter + markdown 正文
   - frontmatter 字段：`name`（调用名）、`description`（一句话说明**什么时候该用它**——这是触发的关键）、可选 `allowed-tools`（该 skill 执行期间限制工具集）
   - 正文：注入对话的提示词/操作步骤，支持 `$ARGUMENTS` 占位符替换用户参数
   - 目录内可放辅助文件（脚本、模板），正文里引用相对路径
2. 两级加载位置：`~/.minicode/skills/`（用户级）、`<项目>/.minicode/skills/`（项目级，同名覆盖用户级）
3. **渐进式披露（progressive disclosure，本节的核心思想）**：启动时只把所有 skill 的 `name + description` 做成清单注入 system prompt；**正文只在被调用时才读取**并作为消息注入——skill 再多也几乎不占上下文
4. 两种触发方式：
   - 用户触发：输入 `/skill名 参数`，正文做 `$ARGUMENTS` 替换后作为本轮用户消息
   - 模型触发：提供一个 `skill(name)` 工具，模型根据 system prompt 里的 description 清单自主调用，工具返回 skill 正文
5. 内置一个示例 skill（如 `/commit`：检查 git diff、生成规范 commit message）供验收

**验收标准**：
- 项目级 skill 覆盖用户级同名 skill（构造验证）
- `/commit` 实测可用；对模型说「帮我提交代码」（不打斜杠命令）→ 模型自主通过 skill 工具调用 commit skill
- 启动后打印 system prompt，确认只含 skill 清单不含正文（渐进式披露生效）

**学习要点**：skill = 带元数据的提示词文件，本质是上下文工程不是代码；description 决定触发质量；渐进式披露如何解决「能力越多上下文越爆」的矛盾。

### M9d — MCP 客户端

- [ ] 已完成

**实现清单**：
1. 不用现成 SDK，手写最小 MCP 客户端（教学价值最大）：读 `.minicode/mcp.json` 配置 → `subprocess.Popen` 启动 server → stdio 上跑 JSON-RPC 2.0：`initialize` 握手 → `tools/list` 拉取工具清单 → 把远程工具包装成我们的工具协议（`base.py`）混入注册表 → 模型调用时转发 `tools/call`
2. MCP 工具默认走 M3 权限系统的 `execute` 级别（外部代码，最高警惕）
3. 用一个公开的官方示例 server（如 filesystem server）做联调

**验收标准**：配置示例 server 后，模型能列出并成功调用 MCP 工具完成任务；agent 循环代码**零改动**（验证工具层抽象的正确性）。

### 其余扩展

- [ ] M9a：**todo 工具** — agent 自我规划任务清单并在终端展示进度（复现 TodoWrite）
- [ ] M9b：**plan mode** — 切换到只读工具集 + system prompt 追加「只调研和出方案，不许修改」；用户批准方案后换回完整工具集执行（复现 Claude Code 的 plan mode）
- [ ] M9c：**hooks** — 工具执行前后运行用户配置的 shell 命令（如 edit 后自动跑 formatter），hook 非零退出可阻止工具执行
- [ ] M9f：**goal 模式** — `minicode --goal "目标描述"`：不等用户输入，每轮结束后自动注入「继续完成目标；若已完成输出 <DONE>」，直到模型声明完成或达到轮数上限（如 30 轮）；结合 `accept-edits` 权限模式实现无人值守

到这里，Claude Code 的核心架构已全部复现。可以写一篇总结文章：《从 400 行到一个 coding agent：我复现 Claude Code 学到的》。
