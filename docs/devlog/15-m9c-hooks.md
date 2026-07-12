# M9c：hooks

日期：2026-07-13

## 做了什么

复现 Claude Code 的 hooks：`.minicode/hooks.json` 里配置的 shell 命令在工具执行前（pre_tool）/后（post_tool）自动运行。hook 通过环境变量（TOOL_NAME / TOOL_INPUT / TOOL_FILE）拿到上下文；**pre_tool 非零退出会阻止工具执行**，理由喂回模型；post_tool 失败只忽略（事后无法撤销工具效果）。

新增 `minicode/hooks.py`，`agent.py` 的 `_execute_tool` 在权限检查后、执行前后各加一个 hook 点。

## 关键设计

hooks 解决"确定性自动化"：有些事希望**每次都发生**（审计日志、编辑后格式化、危险操作前置校验），交给提示词模型会忘，写成 hook 是机制保证。这和 M5 读后编辑约束、M9b 工具集物理切换是同一哲学的第三次出现：**能用机制保证的，不靠提示词。**

执行顺序：权限检查 → pre_tool hook → 工具执行 → post_tool hook。权限在前——用户没批准的操作连 hook 都不该跑。

## 验收

- ✅ 单测：pre hook exit 1 真实阻止了 write_file（文件不存在 + 阻止理由进 messages）；post hook 收到正确的 TOOL_NAME/TOOL_FILE 环境变量；无 tool 字段的 hook 匹配所有工具
- ✅ 真实验收：配置 post_tool 审计 hook 后跑 goal 任务，audit.log 记录了两次 write_file 的目标文件（greet.py、test_greet.py）——hook 在真实模型驱动的流程里透明生效

## 跟着学

`minicode/hooks.py` 顶部 docstring + `agent.py` 里两个 hook 调用点的位置——思考"为什么权限检查要在 pre hook 之前"。
