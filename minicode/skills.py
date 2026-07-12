"""Skill 系统：markdown 定义的可复用操作指引（复现 Claude Code 的 Agent Skills）。

一个 skill = 一个目录 + 一个 SKILL.md：

    .minicode/skills/commit/SKILL.md
    ├── frontmatter（YAML 元数据）：name + description
    └── 正文（markdown）：注入对话的提示词/操作步骤，支持 $ARGUMENTS 占位符

核心思想是**渐进式披露（progressive disclosure）**：启动时只把所有 skill 的
name + description 做成清单放进 system prompt（"目录"），正文只在被触发时
才读取（"翻书"）。这解决了一个根本矛盾——想让 agent 会的东西越多，注入的
提示词就越多，上下文就越爆。skill 再多，闲置成本也只有一行描述。

要点：skill 注入的是**知识**（怎么做某件事的流程），不是**能力**（能力来自
工具）。skill 系统属于上下文工程，不是插件系统——这也是它和 MCP（M9d，
接入外部工具=扩展能力）的本质区别。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    path: Path  # SKILL.md 的路径，正文按需读取（渐进式披露）

    def load_body(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        _, body = _split_frontmatter(text)
        return body.strip()


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """把 SKILL.md 切成 (frontmatter 字典, 正文)。

    只支持 `key: value` 的最简 YAML 子集——够用就好，不引入 yaml 依赖。
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, parts[2]


def _scan_dir(skills_dir: Path) -> dict[str, Skill]:
    found: dict[str, Skill] = {}
    if not skills_dir.is_dir():
        return found
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        meta, _ = _split_frontmatter(skill_file.read_text(encoding="utf-8"))
        name = meta.get("name") or skill_file.parent.name
        description = meta.get("description", "")
        if description:  # 没有 description 的 skill 无法被触发，直接跳过
            found[name] = Skill(name=name, description=description, path=skill_file)
    return found


def discover_skills(cwd: Path | None = None) -> dict[str, Skill]:
    """发现可用 skill。项目级（<cwd>/.minicode/skills/）覆盖用户级
    （~/.minicode/skills/）的同名 skill——越靠近项目的配置优先级越高，
    和 M4 记忆分层的思想一致。"""
    cwd = cwd or Path.cwd()
    skills = _scan_dir(Path.home() / ".minicode" / "skills")
    skills.update(_scan_dir(cwd / ".minicode" / "skills"))
    return skills


def skills_index(skills: dict[str, Skill]) -> str:
    """生成给 system prompt 的清单——只有 name + description，没有正文。"""
    lines = [f"- {s.name}: {s.description}" for s in skills.values()]
    return "\n".join(lines)


def render_skill(skill: Skill, arguments: str = "") -> str:
    """加载正文并替换 $ARGUMENTS 占位符，得到最终注入对话的提示词。"""
    return skill.load_body().replace("$ARGUMENTS", arguments)
