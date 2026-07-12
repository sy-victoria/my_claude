# M9d：手写 MCP 客户端

日期：2026-07-13

## 做了什么

不用官方 SDK，手写最小 MCP 客户端：stdio 上的 JSON-RPC 2.0（一行一条消息）→ `initialize` 三步握手 → `tools/list` 拉工具清单 → 包装成本地 `Tool` 协议混入注册表 → 模型调用时转发 `tools/call`。另写了一个迷你 MCP server（`tests/mini_mcp_server.py`，提供 add 工具）作为测试与验收对端——顺便成为"server 端长什么样"的教学示例。

新增：`minicode/mcp_client.py`、`tests/mini_mcp_server.py`、`tests/test_mcp.py`（6 个测试，真实拉起子进程做集成测试）；`cli.py` 入口加载 `.minicode/mcp.json`。

## 关键设计决策

**1. agent 循环零改动——这是本里程碑真正要验证的东西。**
远程工具包装成 `Tool(name, description, input_schema, run)` 后，agent 循环、权限系统、CLI 日志对它和本地工具一视同仁。`git diff` 可证：`agent.py` 在本里程碑一行未改。这是 M1 工具层抽象设计的回报：**能力的来源（本地函数还是远程进程）是工具层的实现细节**。

**2. MCP 工具统一 execute 权限级别 + `mcp__<server>__` 命名前缀。**
外部代码按最高警惕对待（default 模式下每次询问）；前缀防撞名，也让用户在确认时一眼看出"这是外部工具"。两者都是 Claude Code 的同款约定。

**3. server 在 CLI 入口加载一次，不在 Agent 构造函数里。**
否则每个子 agent（M7 task）都会重复拉起 server 子进程。资源的生命周期跟着进程入口走，不跟着对象走。

**4. 关于 DeepSeek「不支持 MCP」的说明（CLAUDE.md 3.2 预留的问题）。**
DeepSeek 端点不支持的是**服务端 MCP**（API 层面直连 MCP server）。我们的实现里，MCP 工具发给模型时就是普通 tools 数组条目，模型完全不知道背后是个子进程——所以不受该限制影响。验收通过即为实证。

**5. skill vs MCP（面试高频对比，现在两份代码都在手边）。**
skill（M9e）注入**知识**：一段教模型"怎么做"的提示词，属于上下文工程；MCP 接入**能力**：模型原本做不到的操作（本例是远程计算），属于工具系统。代码上的体现：skill 的产出进 messages（提示词），MCP 的产出是 tool_result（执行结果）。

## 验收结果

- ✅ 93 个测试全绿（MCP 集成测试真实拉起子进程：握手/清单/调用/错误/配置加载）
- ✅ 真实验收：配置 mcp.json → 加载出 `mcp__calc__add` → 对模型说「用可用的加法工具算 13579 + 86421」→ 模型正确调用远程工具 → 返回 100000
- ✅ agent 循环零改动（本里程碑 `agent.py` 无 diff）
- 说明：roadmap 原文建议用官方 filesystem server 联调，为避免引入 node/npx 环境依赖，改用自写迷你 server（协议实现是标准的，教学价值更高）。如实记录这一偏差。

## 跟着学

1. `minicode/mcp_client.py` 的 `McpServer`——整个 MCP 客户端骨架不到 100 行，握手/请求/通知各是什么一目了然。
2. `tests/mini_mcp_server.py`——server 端视角再看一遍协议，两边对照读，MCP 就"祛魅"了。
3. `wrap_as_tools()` 的 lambda 闭包——远程调用被包装成和本地函数同形的 `run`，这一行就是"协议适配层"的全部。

## 遗留问题

- 只支持 stdio 传输（MCP 还有 HTTP/SSE）；只做了 tools（MCP 还有 resources/prompts）。骨架已具备，均可按需扩展。
- server 子进程没有优雅关闭钩子（进程退出时靠 OS 回收）；学习项目可接受。
