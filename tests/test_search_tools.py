"""M5 工具的纯逻辑测试：glob / grep / write_file + 读后编辑约束。"""

from types import SimpleNamespace

from minicode.agent import Agent
from minicode.permissions import PermissionManager
from minicode.tools.glob_files import glob_tool
from minicode.tools.grep_files import grep_tool
from minicode.tools.write_file import write_file_tool


def _project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def calc_total(x):\n    return x\n")
    (tmp_path / "src" / "b.py").write_text("from a import calc_total\n")
    (tmp_path / "readme.md").write_text("docs\n")
    return tmp_path


def test_glob_finds_py_files_recursively(tmp_path):
    _project(tmp_path)

    result = glob_tool.run({"pattern": "**/*.py", "path": str(tmp_path)})

    assert "a.py" in result
    assert "b.py" in result
    assert "readme.md" not in result


def test_glob_no_match_suggests_wider_pattern(tmp_path):
    result = glob_tool.run({"pattern": "**/*.go", "path": str(tmp_path)})

    assert "没有匹配" in result


def test_grep_returns_file_line_content(tmp_path):
    _project(tmp_path)

    result = grep_tool.run({"pattern": r"calc_total", "path": str(tmp_path), "glob": "**/*.py"})

    lines = result.splitlines()
    assert len(lines) == 2
    assert any("a.py:1:" in line for line in lines)
    assert any("b.py:1:" in line for line in lines)


def test_grep_invalid_regex_returns_guidance(tmp_path):
    result = grep_tool.run({"pattern": "([", "path": str(tmp_path)})

    assert "正则表达式无效" in result


def test_grep_skips_binary_files(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01calc")
    (tmp_path / "ok.txt").write_text("calc\n")

    result = grep_tool.run({"pattern": "calc", "path": str(tmp_path)})

    assert "ok.txt" in result
    assert "bin.dat" not in result


def test_write_file_creates_and_overwrites(tmp_path):
    target = tmp_path / "new" / "f.txt"

    r1 = write_file_tool.run({"path": str(target), "content": "v1"})
    r2 = write_file_tool.run({"path": str(target), "content": "v2"})

    assert "创建" in r1
    assert "覆盖" in r2
    assert target.read_text() == "v2"


# ---------- 读后编辑约束（agent 层） ----------


class FakeAPI:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


def _tool_use(name, tool_input):
    return SimpleNamespace(type="tool_use", id="c1", name=name, input=tool_input)


def _final(text):
    return SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
    )


def test_edit_without_prior_read_is_rejected(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n")
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[_tool_use("edit_file", {"path": str(target), "old_str": "x = 1", "new_str": "x = 2"})],
        ),
        _final("好"),
    ]
    agent = Agent(client=FakeAPI(responses), permissions=PermissionManager(mode="yolo", cwd=tmp_path))

    agent.run_turn("改一下")

    assert "必须先读取" in agent.messages[2]["content"][0]["content"]
    assert target.read_text() == "x = 1\n"  # 未被修改


def test_edit_after_read_succeeds(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n")
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[_tool_use("read_file", {"path": str(target)})],
        ),
        SimpleNamespace(
            stop_reason="tool_use",
            content=[_tool_use("edit_file", {"path": str(target), "old_str": "x = 1", "new_str": "x = 2"})],
        ),
        _final("改好了"),
    ]
    agent = Agent(client=FakeAPI(responses), permissions=PermissionManager(mode="yolo", cwd=tmp_path))

    agent.run_turn("改一下")

    assert target.read_text() == "x = 2\n"


def test_creating_new_file_needs_no_prior_read(tmp_path):
    target = tmp_path / "new.py"
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[_tool_use("edit_file", {"path": str(target), "old_str": "", "new_str": "y = 1\n"})],
        ),
        _final("建好了"),
    ]
    agent = Agent(client=FakeAPI(responses), permissions=PermissionManager(mode="yolo", cwd=tmp_path))

    agent.run_turn("建个文件")

    assert target.read_text() == "y = 1\n"
