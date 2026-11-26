"""Offline evaluation contract: pinned selection, cross-file patch, metrics."""

import json

from minicode.eval import compare, export_patch, load_instances, run_fault_injection, summarize


def test_pinned_manifest_selects_only_requested_instances(tmp_path):
    data = [{"instance_id": "b", "repo": "r", "base_commit": "0", "problem_statement": "b"},
            {"instance_id": "a", "repo": "r", "base_commit": "0", "problem_statement": "a"}]
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data))
    manifest = {"instance_ids": ["a", "b"]}
    assert [row["instance_id"] for row in load_instances(manifest, path)] == ["a", "b"]


def test_export_patch_includes_cross_file_changes(tmp_path):
    import subprocess

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)

    git("init", "-q")
    (tmp_path / "a.py").write_text("value = 1\n")
    (tmp_path / "b.py").write_text("from a import value\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base")
    (tmp_path / "a.py").write_text("value = 2\n")
    (tmp_path / "b.py").write_text("from a import value\nassert value == 2\n")
    patch = export_patch(tmp_path)
    assert "diff --git a/a.py b/a.py" in patch
    assert "diff --git a/b.py b/b.py" in patch


def test_report_counts_resolved_tokens_and_recovery():
    metrics = [{"instance_id": "a", "usage_tokens": 10, "tool_calls": 2,
                "elapsed_seconds": 1, "recovery_attempted": True, "recovered": True},
               {"instance_id": "b", "usage_tokens": 20, "tool_calls": 3,
                "elapsed_seconds": 2, "recovery_attempted": True, "recovered": False}]
    report = summarize(metrics, {"a"})
    assert report["resolve_rate"] == 0.5
    assert report["total_tokens"] == 30
    assert report["total_tool_calls"] == 5
    assert report["recovery_success_rate"] == 0.5


def test_fault_boundaries_recover_without_replaying_writes():
    outcomes = run_fault_injection()
    assert len(outcomes) == 5
    assert all(item["recovered"] for item in outcomes)


def test_compare_rejects_mismatched_task_sets():
    import pytest

    with pytest.raises(ValueError, match="实例 ID"):
        compare([{"instance_id": "a"}], [{"instance_id": "b"}], set(), set())
