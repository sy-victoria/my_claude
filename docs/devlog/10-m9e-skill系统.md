# M9e：Skill 系统

日期：2026-07-13

## 做了什么

复现 Claude Code 的 Agent Skills：markdown 定义的可复用操作指引，双触发路径（用户 `/名字`、模型自主），核心是**渐进式披露**。

新增/修改：`minicode/skills.py`（发现/解析/渲染）、`tools/skill.py`（模型触发通道）、`prompts.py`（skill 清单区块）、`cli.py`（`/名字 参数` 用户触发）、示例 skill `.minicode/skills/commit/SKILL.md`、`tests/test_skills.py`（7 个测试）。

## 关键设计决策

**1. skill 的组成 = frontmatter（name + description）+ 正文 + 可选辅助文件。**
description 是触发器——模型靠它判断"当前任务该不该用这个 skill"；正文才是操作指引。**skill 注入的是知识（怎么做），不是能力（能做什么，能力来自工具）**——skill 系统属于上下文工程，不是插件系统。这也是 skill 和 MCP 的本质区别（M9d 做完可以对照两份代码体会）。

**2. 渐进式披露：启动时只注入"目录"，被触发才"翻书"。**
system prompt 里只有每个 skill 的一行 name + description；正文在 skill 工具被调用或 `/名字` 输入时才从磁盘读取。这解决了"能力越多上下文越爆"的根本矛盾——skill 再多，闲置成本每个只有一行。验收里结构性断言了这一点（正文字符串不在 system prompt 中）。

**3. 两级目录 + 项目覆盖用户。**
`~/.minicode/skills/`（用户级）与 `<项目>/.minicode/skills/`（项目级），同名时项目级胜出——和 M4 记忆分层同一个原则：越贴近项目的配置优先级越高。

**4. frontmatter 解析只支持 `key: value` 最简子集，不引入 yaml 依赖。**
够用就好；CLAUDE.md 的依赖红线优先于解析器的完备性。

## 验收结果

- ✅ `uv run pytest` 84 个全绿（含项目覆盖用户级、清单不含正文等结构性测试）
- ✅ 渐进式披露：真实 agent 的 system prompt 含 "commit" 清单行、不含正文步骤（脚本断言）
- ✅ **模型自主触发**：临时 git 仓库里只说「帮我提交一下代码」（没有打 /commit）→ 模型第一个工具调用就是 `skill(name=commit)`，随后按指引 git status/diff → 生成规范 message → 真实产生提交 `feat: 添加用户登录函数`
- ✅ 用户触发路径 `/commit 参数` 由 `resolve_skill_input` 处理（单测覆盖渲染与 $ARGUMENTS 替换）

## 跟着学

1. `minicode/skills.py` 顶部 docstring + `skills_index()`——渐进式披露的完整故事。
2. `.minicode/skills/commit/SKILL.md`——一个真实 skill 长什么样；注意 description 是写给"模型的触发判断"看的，正文是写给"模型的执行"看的，受众不同措辞不同。
3. 验收日志第一行 `> tool: skill({'name': 'commit'})`——一行 description 换来的自主触发。

## 遗留问题

- 未实现 `allowed-tools`（skill 执行期间限制工具集）；结构上可以复用 M7 的 tools 参数机制，留作练习。
