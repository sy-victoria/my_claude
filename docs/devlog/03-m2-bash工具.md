# M2：Bash 工具

日期：2026-07-12

## 做了什么

给 agent 加上了执行 shell 命令的能力，并落地 CLAUDE.md 第五节的全部安全约束。M1 里"创建 fizzbuzz.py 并运行"这个注定失败的验收用例，现在全流程跑通了。

新增/修改文件：
- `minicode/tools/bash.py`：bash 工具（黑名单 → 用户确认 → 超时执行 → 截断输出）
- `minicode/config.py`：新增 `BASH_TIMEOUT_SECONDS = 30`、`BASH_MAX_OUTPUT_CHARS = 2000`
- `minicode/tools/__init__.py`：注册 bash 工具
- `minicode/tools/edit_file.py`：description 追加一句"改完代码用 bash 验证"（roadmap 要求的 M1 工具说明更新）
- `tests/test_bash.py`：8 个测试

## 关键设计决策

**1. 三道防线的顺序：黑名单 → 用户确认 → 超时/截断。**
黑名单放在最前面且**不进入确认环节**——`sudo`、`rm -rf /` 这类命令连"问一下用户"的机会都不给，因为确认对话有社会工程风险（用户可能在长会话里疲劳地按 y）。这个顺序本身就是设计：永远不该做的事（黑名单）> 需要人类判断的事（确认）> 技术性保护（超时/截断）。

**2. 确认机制做成可替换的模块级钩子 `ask_user_confirmation`。**
终端交互时是 `input()` 问 y/n；测试和脚本化验收时注入 lambda 替换。为什么不做成 Tool 的构造参数或全局配置类？因为这个钩子在 M3 就会被统一的权限系统取代——它是一块明确的"临时脚手架"，用最便宜的方式实现，等 M3 拆掉时也没有迁移成本。**知道一段代码活不长，就不要给它修豪宅。**

**3. `config` 用 `from minicode import config` 而不是 `from minicode.config import 常量`。**
from-import 会把常量的**值**复制进 bash 模块的命名空间，之后测试再 monkeypatch `config.BASH_TIMEOUT_SECONDS` 就影响不到它了。改成引用模块、调用时取属性，测试就能把超时改成 1 秒来验证超时逻辑（不用真等 30 秒）。这是 Python 测试里一个常见的坑，值得记住。

**4. 非零退出码明确写进返回文本。**
`subprocess` 不会因为命令失败而抛异常（我们没用 `check=True`，这是有意的），所以要主动把 `returncode != 0` 转述给模型——"命令以非零退出码 2 结束"这条信息是模型判断"上一步失败了、需要换个做法"的关键信号。验收场景 2 里模型正是靠这个信号从错误路径中自我恢复的。

## 踩坑记录

**模型臆想了一个不存在的路径，然后自己恢复了。** 场景 2（"跑一下这个项目的测试"）里，模型第一次调用 bash 时执行的是 `cd /Users/ldq/coding-agent && uv run pytest`——注意 `ldq` 这个用户名是它编的（真实路径是 `/Users/limit/coding-agent`）。命令失败后，它自己执行 `pwd && ls -la` 确认真实位置，然后用相对路径重跑成功。

两个教训：
1. 再次验证了"错误信息喂回模型"机制的价值——非零退出码 + stderr 让模型完成了自我纠正，全程无人工干预；
2. 根因是 agent 到现在都不知道自己的 cwd，只能靠猜。这是 M4（环境上下文注入 system prompt）要解决的问题，这已经是第二次在验收里撞到它了（第一次见 M1 devlog 遗留问题）。

另外场景 2 里模型为了"跑测试"这一个任务读了 6 个文件（含整个 CLAUDE.md），消耗了不少上下文——这种"探索型任务污染主上下文"的现象，就是 M6（上下文管理）和 M7（子 agent）存在的理由，先记在这里。

## 验收结果

单元测试：`uv run pytest` 25 个全绿（新增 8 个 bash 测试）。

真实 API 验收（DeepSeek，`scratchpad/m2_verify/` 临时目录 + 本项目目录）：
- ✅ 「创建 fizzbuzz.py 并运行给我看」全流程成功：`edit_file` 创建（这次模型还主动写了函数封装和 docstring）→ `bash: python3 fizzbuzz.py` → 输出 1~15 的正确 FizzBuzz 序列，模型还验证了第 15 项
- ✅ 「跑一下这个项目的测试」→ agent 自主执行 `uv run pytest`（中间经历了一次路径臆想+自我恢复，见踩坑记录），正确汇报 25 个测试全绿及分布
- ✅ 用户拒绝（确认钩子返回 False）→ 模型收到拒绝信息后没有 crash、没有原样重试，而是询问用户顾虑并主动提出用只读的 `list_files` 替代——比预期的"礼貌处理"还好
- ✅ `sleep 60` → 30 秒后被强制终止，模型准确转述了超时机制和错误信息

## 跟着学

1. `minicode/tools/bash.py` 的 `_run()`——从上往下读一遍三道防线的顺序（黑名单 → 确认 → 超时），思考一下：为什么黑名单命中时不问用户？如果把顺序反过来会有什么问题？
2. `minicode/tools/bash.py` 顶部的模块 docstring 里关于 `from minicode import config` 的说明，对照 `tests/test_bash.py` 的 `test_timeout_returns_readable_error` 看 monkeypatch 是怎么生效的——这是"代码怎么写决定了它可不可测"的一个小案例。
3. 验收记录里的场景 2（本文件"踩坑记录"）——一次真实的"模型犯错 → 错误反馈 → 自我恢复"完整链路，读的时候注意模型每一步收到了什么信息、它的下一步为什么是合理的。

## 遗留问题 / 给下个里程碑的备注

- bash 的确认逻辑是临时脚手架，M3 权限系统落地时要**删掉** `ask_user_confirmation` 钩子，统一走 `permissions.check()`（roadmap M3 实现清单第 2 条已写明）。
- agent 仍不知道 cwd/日期/平台，已两次在验收中造成可观察的行为缺陷（M1 蒙对默认参数、M2 臆想路径）——M4 的价值已经被充分论证了。
- 黑名单是子串匹配的教学级实现，容易被绕过（比如 `su` + `do` 拼接）；真实产品需要命令解析。这个局限记录在案，本项目不打算修（超出学习目标）。
