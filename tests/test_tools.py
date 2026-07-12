"""三个文件工具的纯逻辑测试：不调 API，只验证 输入 -> 执行 -> 输出。"""

from minicode.tools.edit_file import edit_file_tool
from minicode.tools.list_files import list_files_tool
from minicode.tools.read_file import read_file_tool


def test_read_file_returns_numbered_lines(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello\nworld\n")

    result = read_file_tool.run({"path": str(f)})

    assert result == "1\thello\n2\tworld"


def test_read_file_missing_returns_error():
    result = read_file_tool.run({"path": "/no/such/file.txt"})

    assert "错误" in result


def test_read_file_on_directory_returns_error(tmp_path):
    result = read_file_tool.run({"path": str(tmp_path)})

    assert "错误" in result


def test_list_files_marks_dirs_with_trailing_slash(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("x")

    result = list_files_tool.run({"path": str(tmp_path)})
    lines = result.splitlines()

    assert "sub/" in lines
    assert "file.txt" in lines


def test_list_files_empty_dir(tmp_path):
    result = list_files_tool.run({"path": str(tmp_path)})

    assert result == "（空目录）"


def test_edit_file_creates_new_file_when_old_str_empty(tmp_path):
    f = tmp_path / "new.py"

    result = edit_file_tool.run({"path": str(f), "old_str": "", "new_str": "print(1)\n"})

    assert "创建" in result
    assert f.read_text() == "print(1)\n"


def test_edit_file_replaces_unique_match(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")

    result = edit_file_tool.run({"path": str(f), "old_str": "x = 1", "new_str": "x = 2"})

    assert "修改" in result
    assert f.read_text() == "x = 2\n"


def test_edit_file_ambiguous_match_returns_helpful_error(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\nx = 1\n")

    result = edit_file_tool.run({"path": str(f), "old_str": "x = 1", "new_str": "x = 2"})

    assert "2 处" in result
    # 文件不应该被改动——匹配歧义时工具不应该猜一个位置替换。
    assert f.read_text() == "x = 1\nx = 1\n"


def test_edit_file_no_match_returns_helpful_error(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")

    result = edit_file_tool.run({"path": str(f), "old_str": "y = 9", "new_str": "y = 10"})

    assert "错误" in result
    assert f.read_text() == "x = 1\n"


def test_edit_file_missing_file_without_empty_old_str_returns_error():
    result = edit_file_tool.run(
        {"path": "/no/such/file.py", "old_str": "x", "new_str": "y"}
    )

    assert "错误" in result
