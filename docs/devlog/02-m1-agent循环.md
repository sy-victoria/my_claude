# M1：最小 agent 循环 + 三个文件工具

日期：2026-07-12

## 做了什么

复现了 Thorsten Ball《How to Build an Agent》的核心闭环：一个能对话、能自主读文件/列目录/改文件的 agent。这是全项目最重要的一步——做完这个，"agent = LLM + 工具 + 循环"就不再是一句口号，而是亲手跑通的 200 多行代码。

新增/重写文件：
- `minicode/tools/base.py`：`Tool` 数据类（name/description/input_schema/run）
- `minicode/tools/read_file.py`、`list_files.py`、`edit_file.py`：三个工具的实现
- `minicode/tools/__init__.py`：`TOOLS` 注册表 + `get_tool()`
- `minicode/agent.py`：`Agent` 类，`run_turn()` 驱动核心循环
- `minicode/cli.py`：最小 REPL
- `tests/test_tools.py`、`tests/test_agent.py`：新增；`tests/test_cli.py`：因为 `main()` 行为变了，重写

## 关键设计决策

**1. 工具用一个 `Tool` dataclass 表达，不用类继承体系。**
一开始的直觉是给每个工具写一个类、继承一个 `BaseTool` 抽象基类。但认真想了一下：工具之间没有共享状态、没有多态调用需求（agent.py 只是遍历 `TOOLS` 拿 schema、按 name 查 `run` 函数执行），一个"四个字段的数据结构 + 一个函数字段"就完全够用。这正是 CLAUDE.md 里"直白就是高级"的一个具体例子——继承体系在这里是纯粹的过度设计。

**2. `_execute_tool` 统一捕获所有工具异常，转成文本返回给模型。**
这是 agent 循环里最容易被忽略但最重要的一行设计：`try/except Exception` 包住 `tool.run()`，异常文本变成 `tool_result`。原因是——**模型看得懂英文/中文错误信息，看不懂 Python Traceback 导致的进程崩溃**。这条设计在真实验收里被意外验证了一次（见"踩坑记录"），效果比预想的还好。

**3. `edit_file` 的错误信息专门为"模型下一步怎么办"设计。**
"匹配到 N 处不唯一"和"完全找不到"是两种不同的错误，分别给了不同的修复建议（前者"加上下文使其唯一"，后者"先 read_file 重新读取确认内容一致"）。这不是随手写的报错文案，是在写 prompt——模型读到这句话后会知道下一步该做什么，而不是重复同样的错误。

**4. `Agent.__init__` 支持注入 `client`，而不是只能传 `api_key`。**
CLAUDE.md 3.4 规定"agent 循环用 mock 的 API 响应测试，不要在测试里真调 API"。要满足这条，`Agent` 必须能接受一个假的"消息客户端"。做法是给构造函数加一个可选的 `client` 参数：传了就直接用，不传才用 `api_key` 建立真实的 `anthropic.Anthropic(...)`。这是一个参数级别的依赖注入，不是引入了什么 DI 容器或 Provider 抽象——满足"直白"的同时解决了可测试性问题。

**5. 没有在 M1 里加任何环境上下文注入（cwd、平台等）。**
验收时能明显感觉到：agent 不知道自己在哪个目录、今天几号——因为这些属于 system prompt 该做的事，而 M1 故意没有实现 system prompt（那是 M4 的内容）。`list_files` 不传 `path` 时默认当前工作目录，模型确实是"蒙对"了默认行为，而不是真的"知道"。这个局限点记下来，M4 做完后可以做一次对比实验。

## 踩坑记录

**踩到的"坑"其实是一次意外的设计验证。** 场景 4（"创建 fizzbuzz.py 并运行给我看"）里，模型自己编造了一个不存在的工具名 `run_command` 并尝试调用。我们的 `get_tool()` 返回 `None`，`_execute_tool` 按设计返回了 `"错误：未知工具 run_command"` 这条 `tool_result`。模型看到这条错误后没有崩溃、没有重复尝试，而是**在最终回复里主动向用户道歉，解释自己目前没有执行命令的工具，并且给出了手动运行的建议**。

这不是我们特意设计的分支逻辑，纯粹是"错误信息喂回模型"这条通用机制自然覆盖到的场景。记下来是因为它比任何设计文档都更有说服力地证明了 M1 architecture doc 里那句话：**"错误信息也是 prompt"**。

其余没有遇到需要绕过或返工的技术问题。

## 验收结果

在 `scratchpad/m1_verify/`（临时测试目录，含 `config.txt`、`readme.md`、`calc.py`、`util.py` 四个种子文件）里用真实 DeepSeek API 做了 5 轮连续对话验证：

- ✅ 「这个目录里有什么文件」→ 自主调用 `list_files({})`，正确列出 4 个文件并用表格总结
- ✅ 「读一下 readme.md 并用一句话解释」→ 自主调用 `read_file({'path': 'readme.md'})`，总结准确
- ✅ 「把 config.txt 里的 A 改成 B」→ 先 `read_file` 确认内容，再 `edit_file({'old_str': 'APP_NAME=A', 'new_str': 'APP_NAME=B'})`；实际检查文件内容确认已改为 `APP_NAME=B`
- ✅ 「创建 fizzbuzz.py 并运行给我看」→ `edit_file` 创建了正确的 fizzbuzz 逻辑（实测 `os.path.exists("fizzbuzz.py")` 为 `True`），运行环节因为没有 bash 工具而失败，模型对此给出了得体的解释（见踩坑记录）——这正是 roadmap 里预告的"这正好引出 M2"
- ✅ 「读一下这个目录里所有的 .py 文件并总结」→ 一次用户输入内触发了两次连续 `read_file` 调用（`calc.py`、`util.py`），循环正常处理多工具调用，总结内容正确
- ✅ `uv run pytest`：17 个测试全绿（8 个工具测试 + 5 个 agent 循环 mock 测试 + 2 个 cli 测试 + 2 个 M0 遗留测试更新）
- ✅ 额外验证：真实交互式 REPL（`echo ... | uv run minicode`）端到端跑通，欢迎语、档位、工具日志、`exit` 退出都正常

## 跟着学

1. `minicode/agent.py` 的 `run_turn()`（第 70~95 行左右）——整个项目最值得反复读的一段代码。建议对照 `docs/01-architecture.md` 第 1 节的伪代码逐行读，然后回头看 `_execute_tool` 里的 `try/except`，体会"模型不执行任何东西，只输出意图"这句话的具体含义。
2. `minicode/tools/edit_file.py` 的 `_run()` 函数——重点看三个分支（创建新文件 / 匹配到 0 处 / 匹配到多处）的错误信息怎么写。这是"错误信息即 prompt"在代码里的具体样子。
3. `tests/test_agent.py` 的 `FakeMessagesAPI`——一个只有十几行的假对象就完成了整个 agent 循环的测试隔离，看完再回头看 `agent.py` 里 `_MessagesClient` 这个 `Protocol` 声明，理解 Python 里"鸭子类型"式依赖注入是怎么做到"不需要框架也能测试"的。

## 遗留问题 / 给下个里程碑的备注

- agent 目前完全不知道自己所在的目录、日期等环境信息，纯粹靠工具的默认参数"蒙对"——这是 M4（系统提示词）要解决的问题，届时可以做一次对比实验记进 devlog。
- `edit_file` 目前没有强制"编辑前必须先读过"的约束（M5 会加：agent 端记录已读文件集合）。这次验收里模型是自发地在改文件前先读了一次，但这只是模型的良好习惯，不是我们代码强制的，不能依赖这一点。
- 权限确认目前完全没有——`edit_file` 可以无提示地创建/修改任何路径下的文件（只要模型给出的 path 合法）。M3 会补上确认机制；在那之前使用时要注意只在临时测试目录里对话，不要在重要目录里跑。
