"""工具协议定义。

每个工具由四部分组成：name（工具名）、description（给模型看的说明书，本质
是 prompt engineering——模型选不选、会不会用对一个工具几乎全靠它）、
input_schema（JSON Schema，随请求发给模型）、run（本地执行函数）。

用一个 dataclass 表达这四个字段就够了，不需要类继承体系或工厂——这是
CLAUDE.md 里"直白就是高级"的一个例子：工具之间没有共享状态和多态需求，
一个普通的数据结构 + 一个函数字段就能满足全部场景。
"""

from dataclasses import dataclass
from typing import Any, Callable

# 每个工具的本地执行函数：输入是模型传来的参数字典，输出是要喂回模型的文本。
# 执行函数不应该抛出未捕获的异常——调用方（agent.py）会兜底捕获，但工具自己
# 把已知的错误情况（文件不存在等）转换成清晰的错误文本，体验会更好。
ToolFunction = Callable[[dict[str, Any]], str]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    run: ToolFunction
    # 危险级别，权限系统（permissions.py）据此决定放行还是询问用户：
    #   "read"    只读，不改变任何东西（read_file / list_files）
    #   "write"   会修改文件（edit_file）
    #   "execute" 会执行任意代码，危险级别最高（bash）
    permission_level: str = "read"

    def to_api_schema(self) -> dict[str, Any]:
        """转换成 Anthropic `messages.create(tools=...)` 需要的格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
