# 终端体验与 Slash 命令

> 写给项目所有者：这不是 roadmap 里的正式里程碑，而是 M8/M9 做完之后，
> 把终端交互往 Claude Code 的「神似」方向打磨的一轮改动说明。
> 代码改动在 `minicode/cli.py`、`minicode/session.py`、`minicode/agent.py`。

## 1. 斜杠命令是什么？

在 REPL 提示符下，以 `/` 开头的输入**不会发给模型**，而是由本地 Python
直接处理。这叫 **slash 命令**（斜杠命令）。

```
🐳 (sonnet) > /help        ← 本地命令：打印帮助，不调 API
🐳 (sonnet) > 帮我读一下 README  ← 普通对话：进入 agent 循环，会调 API
```

为什么要有这层，而不是全让模型猜？

1. **确定性**：切模型、切权限、清历史这类操作必须 100% 立刻生效，不能依赖模型是否「理解对了」。
2. **省钱**：`/cost`、`/help` 不消耗 token。
3. **和 Claude Code 对齐**：`/model`、`/compact`、`/clear` 等是同类产品的通用约定。

Skill（M9e）也走 `/名字` 语法，但语义不同：`/commit 修复登录` 会把 skill
正文渲染成**本轮用户消息**再交给 agent 循环；内置 slash 则本地处理完就结束。

主循环里的分发顺序（`cli.py` 的 `while True`）：

```
用户输入以 / 开头？
  ├─ 是内置命令（/help /model /mode …）→ 本地处理
  ├─ 是已发现的 skill 名 → 渲染 skill 正文 → agent.run_turn(...)
  └─ 都不是 → 提示未知命令
```

## 2. 当前内置命令一览

| 命令 | 作用 | 不带参数时 |
|---|---|---|
| `/help` | 打印命令列表 | — |
| `/clear` | 清空当前 `messages` | — |
| `/compact` | 手动触发上下文压缩 | — |
| `/cost` | 显示 token 用量 | — |
| `/model` | 切换档位 sonnet / opus | 弹出编号菜单选择 |
| `/mode` | 切换权限 default / accept-edits / yolo | 弹出编号菜单选择 |
| `/plan` | 开关计划模式 on / off | 弹出编号菜单选择 |
| `/resume` | 从历史会话里选一个恢复 | 弹出最近会话列表 |
| `exit` / Ctrl+D | 退出 | — |

带参数的老用法仍然可用，例如：

```
/model opus
/mode yolo
/plan on
```

不带参数时走交互式菜单（仿 Claude Code），三个切换命令共用
`_prompt_from_list()`，避免三份重复渲染代码。

## 3. 这轮「神似 Claude Code」改了什么

### 3.1 交互命令统一成菜单式

之前 `/model` 不带参数只回一句「用法：/model sonnet|opus」，体验生硬。
现在不带参数会打印可选列表、标出「(当前)」、用序号选择。

涉及：`prompt_model_choice` / `prompt_mode_choice` / `prompt_plan_choice`。

### 3.2 新增运行时 `/resume`

以前只能 `minicode --resume` 在**启动时**恢复最近一次会话。
现在会话中途也能 `/resume` 从列表里挑历史会话（当前对话会被替换）。

`session.py` 为此拆出：

- `list_sessions(limit)` — 最近会话，新到旧
- `load(path)` — 读指定文件
- `preview(path)` — 摘第一条用户消息做列表预览
- `load_latest()` — 改为复用上面两个

### 3.3 工具调用日志改成 `⏺` / `⎿` + 彩色 diff

Claude Code 风格：

```
⏺ edit_file(hello.py)
  -print('hi')
  +print('hello world')
```

实现要点：

- `Agent.on_tool_result(name, tool_input, result)`：工具执行完后回调一次
  （成功 / 拒绝 / 报错都会触发）
- `_execute_tool` 拆出 `_run_tool`，保证回调只挂在一个出口
- `edit_file` 成功时用入参里的 `old_str` / `new_str` 走 `difflib`，
  **不用再读一遍磁盘**

### 3.4 底部状态行显示上下文占比

每轮回复结束后：

```
  context: 1234 tokens（1%） · sonnet（deepseek-v4-flash）
```

提示符本身也带当前档位：`🐳 (sonnet) >`，`/model` 切换后立刻可见。

### 3.5 品牌与启动体验（更早一轮）

- 启动横幅：`Panel` 包住「minicode + 档位 + cwd」
- 配色：DeepSeek 品牌蓝（诚实反映后端，不是硬抄 Anthropic 橙）
- 小宠物：`🐳`（spinner 与提示符共用）
- 等待时的随机动词（Musing / Pondering …）保留

### 3.6 刻意没做的

Claude Code 那种「打字时实时变形的圆角输入框」需要
`prompt_toolkit` / `textual` 等新依赖。本项目依赖红线只放行
`anthropic` / `rich` / `pytest`，所以这轮只用 rich 做「神似」，不引入新包。

## 4. 和核心架构的关系

Slash / UI **不在 agent 循环里**。它们是交互层的装饰：

```
cli.py（slash、菜单、⏺ 渲染、spinner）
   │
   ▼  回调挂钩，不反向依赖
agent.py（messages + tools + loop）
```

设计原则：

- `handle_slash(command, agent) -> str` 尽量保持**纯函数**（好测）
- 需要读键盘的交互放在 `prompt_*_choice`，只在主循环调用
- 展示用回调（`on_tool_call` / `on_tool_result` / `on_compact`）事后挂上，
  不污染 Agent 的必需构造参数

## 5. 跟着学（建议阅读顺序）

1. `minicode/cli.py` — `HELP_TEXT` 与 `handle_slash`：命令表与纯逻辑分发
2. `minicode/cli.py` — `_prompt_from_list` 与主循环里的 `pickers`：交互菜单如何挂上
3. `minicode/cli.py` — `_print_tool_call` / `_print_tool_result` / `_print_edit_diff`
4. `minicode/agent.py` — `on_tool_result` 与 `_run_tool`：回调为什么只挂一个出口
5. `minicode/session.py` — `list_sessions` / `preview`：`/resume` 的数据侧

## 6. 验证情况（本轮）

- `uv run pytest`：100 passed
- 手工烟测：`list_files` / `bash` 错误结果 / `edit_file` 彩色 diff 渲染正常

## 7. 未提交状态说明

截至文档编写时，相关代码改动仍在工作区（未 commit）：

- `minicode/cli.py`
- `minicode/session.py`
- `minicode/agent.py`

若需要纳入版本历史，建议单独 commit，message 示例：

```text
UI: slash 菜单式交互 + /resume + ⏺/diff 工具渲染
```
