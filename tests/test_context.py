"""上下文管理测试：token 跟踪、compaction 切分与合并、agent 集成、read 分页。"""

from types import SimpleNamespace

from minicode import config
from minicode.agent import Agent
from minicode.context import ContextTracker, merge_summary, split_for_compaction
from minicode.tools.read_file import read_file_tool


def _resp(text, input_tokens=100, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=10),
    )


class FakeAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def test_tracker_records_usage():
    tracker = ContextTracker()
    tracker.record(_resp("x", input_tokens=1234))

    assert tracker.last_input_tokens == 1234
    assert tracker.cumulative_tokens == 1244


def test_tracker_counts_cached_tokens():
    """启用 prompt 缓存的后端把命中部分报在 cache_read_input_tokens 里，
    上下文体积必须加总，否则 compaction 永远不触发（M6 验收踩到的真坑）。"""
    tracker = ContextTracker()
    resp = _resp("x", input_tokens=75)
    resp.usage.cache_read_input_tokens = 2500

    tracker.record(resp)

    assert tracker.last_input_tokens == 2575


def test_should_compact_uses_threshold(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_WINDOW_TOKENS", 1000)
    monkeypatch.setattr(config, "COMPACT_THRESHOLD", 0.7)
    tracker = ContextTracker()

    tracker.record(_resp("x", input_tokens=699))
    assert not tracker.should_compact()
    tracker.record(_resp("x", input_tokens=700))
    assert tracker.should_compact()


def test_split_keeps_from_last_real_user_input():
    messages = [
        {"role": "user", "content": "任务一"},
        {"role": "assistant", "content": [{"type": "text", "text": "好"}]},
        {"role": "user", "content": "任务二"},
        {"role": "assistant", "content": [{"type": "tool_use"}]},
        {"role": "user", "content": [{"type": "tool_result"}]},  # 非真实用户输入
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ]

    older, recent = split_for_compaction(messages)

    assert len(older) == 2  # 任务一那轮
    assert recent[0]["content"] == "任务二"  # tool_use/result 对没有被拆开


def test_merge_summary_keeps_roles_alternating():
    recent = [
        {"role": "user", "content": "任务二"},
        {"role": "assistant", "content": [{"type": "text", "text": "好"}]},
    ]

    merged = merge_summary("这是摘要", recent)

    assert len(merged) == 2
    assert merged[0]["role"] == "user"
    assert "这是摘要" in merged[0]["content"]
    assert "任务二" in merged[0]["content"]


def test_agent_compacts_at_turn_start(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT_WINDOW_TOKENS", 1000)
    monkeypatch.setattr(config, "COMPACT_THRESHOLD", 0.5)

    fake = FakeAPI([
        _resp("回答一", input_tokens=100),
        _resp("回答二", input_tokens=900),  # 超阈值，下一轮开始时应触发压缩
        _resp("这是历史摘要"),               # 压缩用的总结调用
        _resp("回答三", input_tokens=200),
    ])
    agent = Agent(client=fake)

    agent.run_turn("任务一")
    agent.run_turn("任务二")
    assert len(agent.messages) == 4

    events = []
    agent.on_compact = lambda b, a: events.append((b, a))
    reply = agent.run_turn("任务三")

    assert reply == "回答三"
    assert events == [(4, 2)]
    # 压缩后：摘要并入"任务二"消息 + 回答二 + 任务三 + 回答三
    assert "这是历史摘要" in agent.messages[0]["content"]
    assert "任务一" not in str(agent.messages)  # 旧原文已被替换


def test_read_file_pagination(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 101)))

    result = read_file_tool.run({"path": str(f), "offset": 11, "limit": 5})

    assert result.splitlines()[0] == "11\tline11"
    assert "本次显示第 11~15 行" in result


def test_read_file_default_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "READ_MAX_LINES", 10)
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 101)))

    result = read_file_tool.run({"path": str(f)})

    assert "line10" in result
    assert "line11" not in result.replace("[文件共", "")
    assert "文件共 100 行" in result
