# M7：子 Agent（task 工具）

日期：2026-07-13

## 做了什么

复现 Claude Code 的 Task 工具：主 agent 可以把探索型任务派给一个独立上下文的子 agent，只拿回结论。为此先给 `Agent` 类加了两个通用能力（自定义工具集、单轮最大循环数），然后 task 工具本身只有 30 行核心逻辑——**子 agent 不是新概念，就是再 new 一个 Agent**。

新增/修改：`minicode/tools/task.py`、`agent.py`（`tools`/`max_loops` 参数）、`tools/__init__.py`（注册）、`prompts.py`（何时派发的指引）、`tests/test_task.py`（4 个测试）。

## 关键设计决策

**1. 子 agent = 新建一个 Agent 实例，全新的空 messages。**
没有任何特殊机制：task 工具的 `_run` 里 `Agent(tools=只读子集, max_loops=15)` 然后 `run_turn(prompt)`，返回最终文本。这正是理解"多 agent 系统"的祛魅时刻——所谓子 agent，本质是用一次独立的对话去换主对话的上下文空间。

**2. 两条防失控铁律，都是结构性保证而不是提示词约束。**
禁递归：子 agent 的工具集物理上不含 task（`SUBAGENT_TOOL_NAMES` 白名单），不是"请不要派生子 agent"这种软约束。轮数上限：`max_loops=15`，模型永远不给最终答案时循环也会强制终止。**能用结构保证的就不要依赖提示词**——提示词会被忽略，结构不会。

**3. 子 agent 只给只读工具。**
探索任务不需要写权限；这也让 task 工具自身可以声明为 read 级（M3 的权限系统自动放行，不打扰用户）——整条链路都改不了任何东西，所以整条链路都是安全的。权限声明的传递性在这里体现得很清楚。

**4. `Agent` 的改动是通用化而不是特判。**
没有加 `is_subagent` 标志，而是把"工具集"和"循环上限"变成任何 Agent 都有的参数。主 agent 恰好用全量工具、不限轮数而已。这样 M9b 的 plan mode（切换只读工具集）可以直接复用同一机制。

## 踩坑记录

无大坑。一个观察：子 agent 选择了逐个 read_file 读完全项目（31 次调用），而不是先 grep 定位再精读——对"全面调查"这个措辞来说不算错，但成本偏高。子 agent 的 system prompt 和主 agent 完全一样，没有针对"你是调查者，先搜索后精读"做特化——Claude Code 给不同 agent 类型配不同提示词，就是为了这类行为调优。记录为已知差距。

## 验收结果

- ✅ `uv run pytest` 68 个全绿
- ✅ 真实验收（在本项目仓库里，只读任务）：「用 task 全面调查权限检查的实现」→ 主 agent 派发 task，子 agent 31 次工具调用读遍项目，返回的报告准确（权限链路、3×3 决策矩阵、文件行号全对）
- ✅ **上下文保护量化验证：子 agent 31 次调用，主 agent messages 仅 4 条**（用户输入、task 调用、结论、最终回复）
- ✅ 子 agent 工具集不含 task/edit/bash（单测结构性断言）；max_loops 强制终止失控循环（单测覆盖）

## 跟着学

1. `minicode/tools/task.py` 全文——重点体会"子 agent 就是再 new 一个 Agent"这件事有多简单，然后想：Claude Code 能并行跑多个子 agent，我们的实现改成并行需要动哪里？（提示：几乎只需要线程/异步包装）
2. `agent.py` 里 `tools` 和 `max_loops` 两个参数的注释——通用化 vs 特判的设计取舍。
3. 验收日志的最后两行数字（31 次子调用 vs 4 条主消息）——给面试官讲子 agent 价值时，用这组数字比讲概念有力得多。

## 遗留问题

- 子 agent 与主 agent 共用 system prompt，没有"调查者"特化（见踩坑记录）。
- task 串行执行，主 agent 干等；并行化是 M9 之后的可选练习。
