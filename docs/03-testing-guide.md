# 个人测试指南 — 怎么自己上手玩 minicode

> 面向项目所有者：每完成一个里程碑，都可以按这份指南亲手验证。放心大胆地玩，
> 玩坏了也没关系——这正是学习的一部分。

## 1. 一次性准备

```bash
# 建一个安全的试验场目录（强烈建议：不要在重要目录里跑 agent）
mkdir -p ~/agent-playground && cd ~/agent-playground

# 设置 API Key（DeepSeek 控制台的 key）
export ANTHROPIC_API_KEY=sk-xxxx
```

提示：`export` 只对当前终端窗口生效。想永久生效，把这行加进 `~/.zshrc`。

## 2. 启动 agent

```bash
cd ~/agent-playground   # 你在哪个目录启动，agent 就在哪个目录干活
uv run --project ~/coding-agent minicode

```

`--project` 参数的意思是"用 coding-agent 项目的虚拟环境来运行"，这样你人在
试验场目录、代码用的还是我们项目的。想用更强的模型档位：加 `--tier opus`。

退出：输入 `exit` 或按 `Ctrl+D`。

## 3. 建议的试玩剧本（按里程碑递进）

**M1 能力（文件操作）：**
- `这个目录里有什么文件？` —— 观察它自主调用 list_files
- `创建一个 hello.py，打印你好` —— 观察 edit_file 创建文件
- `把 hello.py 里的"你好"改成"世界你好"` —— 观察它先 read 再 edit
- 故意刁难：`把 hello.py 里的 xyz 改成 abc`（文件里没有 xyz）—— 观察工具返回的错误信息怎么引导模型认错

**M2 能力（bash）：**
- `写一个计算斐波那契前10项的脚本并运行给我看`
- `看看这个目录的 git 状态`（没有 git 仓库时观察它怎么处理报错）
- `执行 sleep 60` —— 30 秒后观察超时报错
- 在确认提示上输入 `n` 拒绝一次 —— 观察模型怎么应对被拒

**M3 能力（权限）：**
- 分别用 `--mode default`、`--mode accept-edits`、`--mode yolo` 启动，做同一件事（如创建文件），感受询问行为的差别
- 在询问时按 `a`，然后再做一次同类操作 —— 观察白名单生效（不再询问）
- 按 `n` 拒绝一次 bash —— 观察模型换什么姿势完成任务

**M4 能力（系统提示词 + 项目记忆）：**
- 直接问：`今天几号？我在哪个目录？` —— 应该 0 次工具调用直接答对
- 在试验场目录建一个 `AGENT.md`，写一条规则（如"回复我时永远先说『收到老板』"），重启 agent —— 观察行为改变
- 把 AGENT.md 删掉再重启 —— 行为恢复

**M5 能力（搜索 + 精确编辑）：**
- 在一个有点规模的项目里：`把 XXX 函数重命名为 YYY，所有引用一起改` —— 观察 grep → read → edit 的完整流程
- `这个项目里哪些文件用到了 XXX？` —— 观察它选 grep 而不是挨个 read
- 不让它先读就直接改（新会话直接说"把 a.py 第一行改成 xxx"）—— 观察"编辑前必须先读"约束的报错和模型的自我纠正

**M6 能力（上下文管理）：**
- 每轮回复后注意 `[context: N tokens]` 读数，连续读几个大文件看它涨
- 输入 `/compact` 手动压缩，观察消息数变化提示
- 长对话后问"我们最初的任务是什么"—— 验证压缩没有丢掉任务目标

**M7 能力（子 agent）：**
- 在一个大点的项目里：`用 task 工具全面调查 XXX 是怎么实现的` —— 观察缩进的 `>> [sub]` 日志（子 agent 的动作）和主对话只多了一条结论
- 对比实验：同样的调查任务不加"用 task 工具"—— 看主对话被多少中间结果塞满

**M8 能力（终端体验）：**
- 随便问个问题，观察：随机的等待状态词（Musing…）、流式输出、markdown 渲染
- 依次试 `/help` `/cost` `/mode yolo` `/model opus` `/clear`
- 模型回复到一半按 `Ctrl+C` —— 应该回到输入提示符而不是退出程序
- 聊几轮后 `exit`，然后 `uv run --project ~/coding-agent minicode --resume` —— 问它上次聊了什么

**M9 能力（全部扩展）：**
- **skill**：项目里建 `.minicode/skills/`（可参考 coding-agent 仓库自带的 commit skill），然后不打斜杠、只说"帮我提交代码"—— 观察模型自主调用 `skill(commit)`；也可以直接 `/commit 补充要求`
- **plan mode**：`/plan on` 后让它改文件 —— 观察它只出方案改不了（甚至会尝试绕过然后失败，很有意思）；`/plan off` 后说"批准了"
- **MCP**：项目里建 `.minicode/mcp.json` 指向 `tests/mini_mcp_server.py`（配置格式见 `minicode/mcp_client.py` 顶部注释），问它"用加法工具算 123+456"
- **todo**：给一个 3 步以上的任务 —— 观察 ☐/◐/☑ 任务清单的实时流转
- **goal 模式**：`uv run --project ~/coding-agent minicode --mode accept-edits --goal "创建一个xxx并测试"` —— 无人值守跑完
- **hooks**：项目里建 `.minicode/hooks.json`（格式见 `minicode/hooks.py` 顶部注释），比如给 write_file 配个审计日志 post hook

**观察要点（比"能不能跑通"更重要）：**
- 每次 `> tool: xxx(...)` 日志：模型选的工具对吗？参数合理吗？
- 出错之后的下一步：模型是重复犯错还是根据错误信息调整了做法？
- 它"不知道"什么：目前问它"我在哪个目录"它只能猜（M4 才注入环境信息）

## 4. 跑单元测试

```bash
cd ~/coding-agent
uv run pytest -v        # 全部测试
uv run pytest tests/test_bash.py -v   # 只跑某个文件
```

单测**不调 API 不花钱**，随便跑。

## 5. 常见问题

| 现象 | 原因/解法 |
|---|---|
| `错误：请先设置环境变量 ANTHROPIC_API_KEY` | 当前终端没 export，见第 1 节 |
| 启动后卡住不动 | 网络问题或 DeepSeek 服务慢，Ctrl+C 退出重试 |
| 模型答非所问/不调工具 | 正常现象，换个更明确的说法再试；这也是观察 prompt 影响的机会 |
| 担心 agent 改了不该改的文件 | M3 之前 edit_file 没有确认机制——所以只在试验场目录玩 |

## 6. 花费说明

每轮对话是一次或多次 API 调用，DeepSeek 便宜但不是免费。日常试玩用默认
sonnet 档位（flash 模型）足够；`/怎么算钱` 这类问题可以直接问 agent 本身试试。
