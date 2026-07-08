# 学习资源清单（2026-07 调研）

## 必读教程（按顺序）

1. **How to Build an Agent** — Thorsten Ball（Amp）
   https://ampcode.com/notes/how-to-build-an-agent
   M1 的直接蓝本：Go 写的 ~400 行 code-editing agent（read_file / list_files / edit_file 三个工具）。名言："It's an LLM, a loop, and enough tokens."
   Python 改写版：https://medium.com/@jbrathnayake98/how-to-build-an-agent-by-thorsten-ball-python-version-ebbabb8665f6

2. **how to build a coding agent（免费 workshop）** — Geoffrey Huntley
   https://ghuntley.com/agent/ ｜ 代码：https://github.com/ghuntley/how-to-build-a-coding-agent
   从 chatbot 逐步加文件读写、bash、搜索工具的完整 workshop，和我们的里程碑划分思路一致。

3. **Build a Coding Agent from Scratch: The Complete Python Tutorial** — Sid Bharath
   https://sidbharath.com/blog/build-a-coding-agent-python-tutorial/

## Claude Code 架构分析（做完 M1 再读）

4. **官方文档：How the agent loop works**
   https://code.claude.com/docs/en/agent-sdk/agent-loop
5. **Dive into Claude Code**（VILA-Lab，系统性学术分析，含 arXiv 论文）
   https://github.com/VILA-Lab/Dive-into-Claude-Code ｜ https://arxiv.org/html/2604.14228v1
6. **Tracing Claude Code's LLM Traffic** — George Sung
   https://medium.com/@georgesung/tracing-claude-codes-llm-traffic-agentic-loop-sub-agents-tool-use-prompts-7796941806f5
   抓包分析真实请求：agent 循环、子 agent、system prompt 长什么样。
7. **Claude Code: Behind-the-scenes of the master agent loop** — PromptLayer
   https://blog.promptlayer.com/claude-code-behind-the-scenes-of-the-master-agent-loop/
8. **Claude Code Architecture Explained**（DEV Community）
   https://dev.to/brooks_wilson_36fbefbbae4/claude-code-architecture-explained-agent-loop-tool-system-and-permission-model-rust-rewrite-41b2

## 参考实现（对照我们的代码看）

9. **claw-code** — ~5000 行 Python 的 Claude Code 干净重写，架构映射清晰（GitHub 搜 claw-code）
10. **nano-claude-code** — https://github.com/SafeRL-Lab/nano-claude-code 极简可用版
11. **开源复现合集** — https://github.com/chauncygu/collection-claude-code-source-code

## API 文档

12. Anthropic Tool Use 官方文档：https://docs.anthropic.com/en/docs/build-with-claude/tool-use
13. Anthropic《Building Effective Agents》：https://www.anthropic.com/research/building-effective-agents
