"""系统提示词的组装。

system prompt 是 agent 的「性格与操作手册」：模型的基础能力来自预训练，
但它在你的终端里表现成什么样的助手——简洁还是话痨、先查证还是先瞎猜、
改完代码验不验证——全部由这里的文字决定。

Claude Code 的对应做法：它的 system prompt 有数千词，分身份、语气、工具
规范、安全等多个区块，并动态拼接环境信息（cwd、平台、日期、git 状态）和
项目记忆（CLAUDE.md）。我们复现同样的三层结构，每层都大幅精简：

    静态部分（身份/风格/工具规范/安全）
      + 环境区块（cwd、平台、日期、目录一级结构）
      + 项目记忆（AGENT.md，存在才注入）

组装结果通过 SDK 的 `system` 参数传递，不占 messages——这样它在每次请求
里都在场，但永远不会被当成对话历史的一部分。
"""

import platform
from datetime import date
from pathlib import Path

# ---------- 静态部分 ----------
# 下面每一段前的注释解释这段提示词的设计意图（为什么要写这句话）。

# 身份与职责：告诉模型"你是谁、在哪运行、目标是什么"。没有这段时模型会
# 以通用聊天助手自居，倾向于长篇解释而不是动手干活。
_IDENTITY = """\
你是 minicode，一个运行在用户终端里的 coding agent。用户给你任务，你通过
调用工具（读写文件、执行命令）来实际完成它，而不是只给出建议。"""

# 工作风格：约束输出长度和行为习惯。"先探索再回答"抑制模型凭想象编造
# 文件内容/路径（M2 验收里模型臆想过一个不存在的路径）；"改完验证"来自
# Claude Code 的核心习惯——代码不是写完就算，是跑通才算。
# 注意第二条特意排除了 <env> 已提供的信息——M4 验收时发现"先查证"和
# "环境已注入"两条指令会打架：模型宁可调 bash 查 pwd 也不用现成的环境
# 信息。提示词之间会相互作用，加约束时要考虑它和已有指令的组合效果。
_STYLE = """\
工作风格：
- 回答简洁，不要重复工具输出里用户已经看到的内容
- 涉及文件/目录内容的问题，先用工具查证再回答，不要凭记忆或想象编造；
  但 <env> 区块里已提供的信息（当前目录、平台、日期、一级目录结构）可以
  直接引用，不需要再用工具确认
- 修改或创建代码后，尽量用 bash 运行它验证结果
- 任务完成后用一两句话总结做了什么"""

# 工具使用规范：帮模型在多个工具间做对选择。工具自身的 description 说的是
# "怎么用我"，这里说的是"什么场景选谁"——两层配合，减少选错工具的概率。
_TOOL_GUIDE = """\
工具选择：
- 找文件名用 glob；找文件内容用 grep；看目录一层结构用 list_files；
  看完整文件内容用 read_file
- 局部修改文件用 edit_file（之前必须先 read_file 同一个文件）；
  创建新文件或整体重写用 write_file
- 重命名/修改函数前，先 grep 找出定义和所有引用，逐个处理
- 需要大量搜索阅读的调查类任务（"全面调查 X"）派给 task 子 agent，
  避免把大量中间结果塞进当前对话
- 3 步以上的多步骤任务，先用 todo_write 列出任务清单，做的过程中逐项更新状态
- bash 用于运行代码、跑测试、git 操作；能用只读工具完成的事不要用 bash"""

# 安全约束：与权限系统（permissions.py）互为补充——权限系统是机制上的
# 硬约束，这里是提示词层面的软约束，让模型主动避免越界而不是撞上守门人。
_SAFETY = """\
安全约束：
- 只操作当前工作目录内的文件，不要动目录外的东西
- 不执行破坏性命令；被用户拒绝的操作不要原样重试
- 不在任何输出中泄露 API key 等敏感信息"""


def _environment_block(cwd: Path) -> str:
    """环境区块：让模型"知道自己在哪"，不用再猜。

    M1/M2 的验收里模型两次因为不知道 cwd 而出错（蒙默认参数、臆想路径）。
    把 cwd、平台、日期、目录一级结构直接写进 system prompt 后，这类问题
    不需要任何工具调用就能回答——这也是 Claude Code env 区块的做法。
    """
    entries = sorted(cwd.iterdir(), key=lambda e: e.name)[:30]
    listing = "\n".join(
        f"  {e.name}/" if e.is_dir() else f"  {e.name}" for e in entries
    ) or "  （空目录）"
    return f"""\
<env>
当前工作目录: {cwd}
平台: {platform.system()}
今天日期: {date.today().isoformat()}
工作目录的一级结构:
{listing}
</env>"""


def _project_memory(cwd: Path) -> str | None:
    """项目记忆：复现 Claude Code 的 CLAUDE.md 机制（我们的文件名叫 AGENT.md）。

    项目记忆解决的问题是"每次会话都要重复交代的背景"：项目的规范、禁忌、
    常用命令。放进 system prompt 意味着它的优先级高于对话内容，且每次请求
    都在场。
    """
    sections: list[str] = []
    directories = [*reversed(cwd.resolve().parents), cwd.resolve()]
    for directory in directories:
        for name in ("CLAUDE.md", "AGENT.md"):
            memory_file = directory / name
            if memory_file.is_file():
                try:
                    content = memory_file.read_text(encoding="utf-8").strip()
                except UnicodeDecodeError:
                    import locale
                    content = memory_file.read_text(encoding=locale.getpreferredencoding(False)).strip()
                if content:
                    sections.append(f"[{memory_file}]\n{content}")
    return "\n\n".join(sections) if sections else None


def _skills_section(cwd: Path) -> str | None:
    """skill 清单区块（M9e，渐进式披露的"目录"部分）。

    只注入每个 skill 的 name + description，正文在模型调用 skill 工具时
    才加载——skill 数量再多，这里的闲置成本也只是每个一行。
    """
    from minicode import skills  # 局部导入，保持模块依赖单向

    found = skills.discover_skills(cwd)
    if not found:
        return None
    return (
        "可用技能（skill）清单如下。当用户的任务匹配某个 skill 的用途时，"
        "先用 skill 工具加载它的操作指引再执行：\n" + skills.skills_index(found)
    )


def build_system_prompt(cwd: Path | None = None) -> str:
    """组装完整的 system prompt：静态部分 + 环境区块 + 项目记忆 + skill 清单。"""
    cwd = cwd or Path.cwd()
    sections = [_IDENTITY, _STYLE, _TOOL_GUIDE, _SAFETY, _environment_block(cwd)]
    memory = _project_memory(cwd)
    if memory is not None:
        sections.append(memory)
    skills_section = _skills_section(cwd)
    if skills_section is not None:
        sections.append(skills_section)
    return "\n\n".join(sections)
