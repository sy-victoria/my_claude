"""Optional SWE-bench Lite runner and comparable execution metrics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import tempfile
from pathlib import Path
from typing import Any

from minicode.agent import Agent
from minicode.harness import TaskJournal
from minicode.permissions import PermissionManager


def _git(arguments: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return result.stdout


def load_instances(manifest: dict[str, Any], dataset_json: Path | None = None) -> list[dict[str, Any]]:
    """Load only the pinned public issue metadata; never prompt with gold patches."""
    if dataset_json:
        records = json.loads(dataset_json.read_text(encoding="utf-8"))
    else:
        try:
            from datasets import load_dataset  # optional; no dependency in the agent runtime
        except ImportError as exc:
            raise RuntimeError("评测需要可选依赖 datasets：pip install datasets") from exc
        records = load_dataset(manifest["dataset"], split=manifest["split"],
                               revision=manifest["revision"])
    by_id = {item["instance_id"]: item for item in records}
    missing = set(manifest["instance_ids"]) - by_id.keys()
    if missing:
        raise ValueError(f"数据集缺少实例：{sorted(missing)}")
    return [by_id[item_id] for item_id in manifest["instance_ids"]]


def prepare_checkout(instance: dict[str, Any], destination: Path) -> None:
    """Fetch only the base commit so future fix commits are absent from local history."""
    if destination.exists():
        raise FileExistsError(f"评测工作区已存在：{destination}")
    destination.mkdir(parents=True)
    try:
        _git(["init", "-q"], destination)
        _git(["fetch", "--depth=1", "https://github.com/" + instance["repo"] + ".git",
              instance["base_commit"]], destination)
        _git(["checkout", "-q", "--detach", "FETCH_HEAD"], destination)
    except Exception:
        # Leave the checkout for diagnosis; never delete a path after a failed fetch.
        raise


def export_patch(destination: Path) -> str:
    _git(["add", "-N", "."], destination)
    return _git(["diff", "--binary", "HEAD", "--", "."], destination)


def run_sample(manifest: dict[str, Any], output: Path, provider: str, model: str,
               dataset_json: Path | None = None, base_url: str | None = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    predictions: list[dict[str, str]] = []
    metrics: list[dict[str, Any]] = []
    for instance in load_instances(manifest, dataset_json):
        instance_id = instance["instance_id"]
        checkout = output / "worktrees" / instance_id
        prepare_checkout(instance, checkout)
        key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        api_key = None if provider == "ollama" else os.environ.get(key_name)
        if provider != "ollama" and not api_key:
            raise ValueError(f"缺少 {key_name}")
        journal = TaskJournal.create(checkout)
        calls: list[str] = []
        agent = Agent(api_key=api_key, provider=provider, model=model, base_url=base_url,
                      permissions=PermissionManager(mode="yolo", cwd=checkout), journal=journal,
                      on_tool_call=lambda name, _input: calls.append(name))
        prompt = ("请修复以下仓库问题。先检查相关代码，修改后运行适当测试；"
                  "最后简要报告结果。\n\n" + instance["problem_statement"])
        started = time.monotonic()
        try:
            answer = agent.run_turn(prompt)
            status = "complete" if agent.last_stop_reason in ("end_turn", "stop_sequence") else "incomplete"
        except Exception as exc:
            answer, status = str(exc), "error"
            journal.rollback()
        patch = export_patch(checkout)
        predictions.append({"instance_id": instance_id, "model_name_or_path": model,
                            "model_patch": patch})
        metrics.append({"instance_id": instance_id, "status": status,
                        "usage_tokens": agent.context.cumulative_tokens,
                        "tool_calls": len(calls), "elapsed_seconds": round(time.monotonic() - started, 3),
                        "task_id": journal.task_id, "answer": answer})
        (output / "predictions.json").write_text(json.dumps(predictions, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")
        (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2),
                                               encoding="utf-8")


def summarize(metrics: list[dict[str, Any]], resolved_ids: set[str]) -> dict[str, Any]:
    count = len(metrics)
    return {"tasks": count, "resolved": len(resolved_ids & {m["instance_id"] for m in metrics}),
            "resolve_rate": (len(resolved_ids & {m["instance_id"] for m in metrics}) / count if count else 0),
            "total_tokens": sum(m.get("usage_tokens", 0) for m in metrics),
            "total_tool_calls": sum(m.get("tool_calls", 0) for m in metrics),
            "total_seconds": round(sum(m.get("elapsed_seconds", 0) for m in metrics), 3),
            "recovery_success_rate": (
                sum(m.get("recovered", False) for m in metrics) /
                sum(m.get("recovery_attempted", False) for m in metrics)
                if any(m.get("recovery_attempted", False) for m in metrics) else None)}


def compare(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]],
            baseline_resolved: set[str], candidate_resolved: set[str]) -> dict[str, Any]:
    if {m["instance_id"] for m in baseline} != {m["instance_id"] for m in candidate}:
        raise ValueError("对照实验的实例 ID 不一致")
    first = summarize(baseline, baseline_resolved)
    second = summarize(candidate, candidate_resolved)
    return {"baseline": first, "candidate": second,
            "delta": {key: second[key] - first[key] for key in
                      ("resolved", "resolve_rate", "total_tokens", "total_tool_calls", "total_seconds")}}


def load_resolved(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data["resolved_ids"]
    if not isinstance(data, list) or not all(isinstance(value, str) for value in data):
        raise ValueError("需要官方 results.json 或实例 ID 字符串数组")
    return set(data)


def run_fault_injection() -> list[dict[str, Any]]:
    """Exercise recovery at durable boundaries without any model or network call."""
    outcomes = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for phase in ("model_response", "tool_begin", "write_snapshot", "tool_done", "tool_results"):
            workspace = root / phase / "repo"
            workspace.mkdir(parents=True)
            target = workspace / "a.py"
            target.write_text("before", encoding="utf-8")
            journal = TaskJournal.create(workspace, root / phase / "tasks")
            messages = [{"role": "user", "content": "edit"},
                        {"role": "assistant", "content": [{"type": "tool_use", "id": "one",
                         "name": "write_file", "input": {"path": "a.py"}}]}]
            journal.checkpoint(messages, "model_response")
            if phase != "model_response":
                journal.begin_tool("main:one", "write_file", {"path": "a.py"})
            if phase in {"write_snapshot", "tool_done", "tool_results"}:
                journal.before_write("main:one", target)
                target.write_text("after", encoding="utf-8")
            if phase in {"tool_done", "tool_results"}:
                journal.finish_tool("main:one", "已覆盖 a.py")
            if phase == "tool_results":
                journal.checkpoint(messages + [{"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "one", "content": "已覆盖 a.py"}]}],
                    "tool_results")
            restored = TaskJournal.load(journal.task_id, workspace, root / phase / "tasks")
            recovered = restored.recover_messages()
            result = recovered[-1]["content"][0]["content"]
            okay = (result == "已覆盖 a.py") if phase in {"tool_done", "tool_results"} else (
                "禁止自动重放" in result)
            outcomes.append({"instance_id": phase, "recovery_attempted": True,
                             "recovered": okay, "usage_tokens": 0, "tool_calls": 1,
                             "elapsed_seconds": 0})
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m minicode.eval")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--manifest", type=Path, default=Path("docs/eval/swebench-lite-dev5.json"))
    run.add_argument("--dataset-json", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--provider", choices=("anthropic", "openai", "ollama"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url")
    report = commands.add_parser("report")
    report.add_argument("--metrics", type=Path, required=True)
    report.add_argument("--official-results", type=Path, required=True)
    comparison = commands.add_parser("compare")
    for label in ("baseline", "candidate"):
        comparison.add_argument(f"--{label}-metrics", type=Path, required=True)
        comparison.add_argument(f"--{label}-official-results", type=Path, required=True)
    fault = commands.add_parser("fault")
    fault.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        run_sample(manifest, args.output, args.provider, args.model, args.dataset_json,
                   args.base_url)
    elif args.command == "report":
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        resolved = load_resolved(args.official_results)
        print(json.dumps(summarize(metrics, resolved), ensure_ascii=False, indent=2))
    elif args.command == "compare":
        load = lambda path: json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(compare(load(args.baseline_metrics), load(args.candidate_metrics),
                                 load_resolved(args.baseline_official_results),
                                 load_resolved(args.candidate_official_results)),
                         ensure_ascii=False, indent=2))
    else:
        outcomes = run_fault_injection()
        args.output.write_text(json.dumps(outcomes, ensure_ascii=False, indent=2), encoding="utf-8")
        if not all(item["recovered"] for item in outcomes):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
