from __future__ import annotations

import copy
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

from scripts.dev_loop_core import commands_loop, validation
from scripts.dev_loop_core.parser import build_parser
from scripts.dev_loop_core.settings import normalize_config
from scripts.dev_loop_core.workspace import current_git_head, read_state, write_state
from .legacy_support import init_git_repo, write_artifacts


QUOTA_MESSAGE = (
    "The job was not started because recent account payments have failed or your spending limit needs to be increased. "
    "Please check the Billing & plans section in your settings."
)


@pytest.fixture
def cloud_case(workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = workspace_tmp_path / "workspace"
    workspace.mkdir()
    init_git_repo(workspace)
    root = workspace / ".codex" / "dev-loop"
    root.mkdir(parents=True)
    write_artifacts(root)
    head = current_git_head(workspace)
    pr = {"url": "https://github.com/example/repo/pull/1", "headRefName": "codex/test",
          "headRefOid": head, "state": "OPEN", "baseRepository": {"nameWithOwner": "example/repo"}}
    state = {"phase": "cloud_checks", "config": normalize_config({"ci_quota_policy": "local_fallback"}),
             "git": {"branch": "codex/test", "commit": head, "pr_url": pr["url"]}, "blockers": []}
    write_state(root, state)
    checks = [{"name": "ai-quality-gate", "state": "FAILURE", "link": "https://github.com/example/repo/runs/7"}]
    runs = [{"id": 7, "name": "ai-quality-gate", "head_sha": head, "app": {"slug": "github-actions"},
             "status": "completed", "conclusion": "failure", "html_url": checks[0]["link"], "output": {}}]
    case = {"workspace": workspace, "root": root, "checks": checks, "runs": runs, "pr": pr,
            "annotations": [{"message": QUOTA_MESSAGE}], "required": [], "calls": []}

    def gh(_workspace, _executable, args):
        case["calls"].append(args)
        if args[:2] == ["pr", "view"]:
            return copy.deepcopy(case["pr"])
        if args[:2] == ["pr", "checks"]:
            return copy.deepcopy(case["required"] if "--required" in args else case["checks"])
        if args[0] == "api" and "/commits/" in args[1]:
            return [{"check_runs": copy.deepcopy(case["runs"])}]
        if args[0] == "api" and args[1].endswith("/annotations"):
            return [copy.deepcopy(case["annotations"])]
        raise AssertionError(args)

    monkeypatch.setattr(commands_loop, "run_gh_json", gh)
    # Other phase prerequisites have their own end-to-end suite; keep these
    # tests focused on GitHub evidence, real local execution, and persistence.
    monkeypatch.setattr(commands_loop, "assert_phase_prereqs", lambda *_: None)
    return case


def record(case, *commands: str, status: str = "quota-exhausted", timeout: int = 10) -> int:
    arguments = [
        "--root", str(case["root"]), "--workspace", str(case["workspace"]),
        "record-cloud", "--status", status, "--timeout", str(timeout),
    ]
    for command in commands:
        arguments.extend(["--local-check", command])
    args = build_parser().parse_args(arguments)
    return commands_loop.cmd_record_cloud(args)


def python_command(source: str) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline([sys.executable, "-c", source])
    return shlex.join([sys.executable, "-c", source])


def test_local_policy_executes_and_records_fresh_evidence(cloud_case) -> None:
    command = "ai-quality-gate=" + python_command("print('quota replacement executed')")
    assert record(cloud_case, command) == 0
    state = read_state(cloud_case["root"])
    evidence = state["github_actions"]
    assert evidence["status"] == "local_fallback_passed"
    assert evidence["cloud_status"] == "quota-exhausted"
    assert evidence["commit"] == cloud_case["pr"]["headRefOid"]
    assert evidence["local_checks"][0]["exit_code"] == 0
    log = cloud_case["root"] / evidence["local_checks"][0]["log"]
    assert "quota replacement executed" in log.read_text()
    assert validation.cloud_is_current(state, cloud_case["root"], cloud_case["workspace"])
    log.write_text("changed")
    assert not validation.cloud_is_current(state, cloud_case["root"], cloud_case["workspace"])


def test_wait_policy_blocks_without_executing_local_commands_and_resumes(cloud_case) -> None:
    state = read_state(cloud_case["root"])
    state["config"]["ci_quota_policy"] = "wait_for_payment"
    write_state(cloud_case["root"], state)
    assert record(cloud_case, "ai-quality-gate=" + python_command("raise AssertionError('must not run')")) == 1
    state = read_state(cloud_case["root"])
    assert state["phase"] == "cloud_checks"
    assert state["github_actions"]["status"] == "waiting_for_payment"
    assert not state["github_actions"].get("local_checks")
    assert state["blockers"]
    assert not validation.cloud_is_current(state, cloud_case["root"], cloud_case["workspace"])
    args = build_parser().parse_args(["--root", str(cloud_case["root"]), "resolve-blocker", "--reason", "Quota restored"])
    assert commands_loop.cmd_resolve_blocker(args) == 0
    cloud_case["checks"][0]["state"] = "SUCCESS"
    assert record(cloud_case, status="passed") == 0
    assert read_state(cloud_case["root"])["github_actions"]["status"] == "passed"


def test_local_policy_requires_commands_for_all_blocked_checks(cloud_case) -> None:
    assert record(cloud_case) == 1
    state = read_state(cloud_case["root"])
    assert state["github_actions"]["status"] == "local_fallback_required"
    assert state["github_actions"]["pending_local_checks"] == ["ai-quality-gate"]
    assert not state["blockers"]


def test_local_failure_is_not_completion(cloud_case) -> None:
    assert record(cloud_case, "ai-quality-gate=" + python_command("raise SystemExit(2)")) == 1
    state = read_state(cloud_case["root"])
    assert state["github_actions"]["status"] == "local_fallback_failed"
    assert state["github_actions"]["local_checks"][0]["exit_code"] == 2
    assert state["blockers"]
    assert not validation.cloud_is_current(state, cloud_case["root"], cloud_case["workspace"])


@pytest.mark.parametrize("reason", ["code", "foreign_head", "foreign_pr", "missing", "external_app", "mixed_failure"])
def test_non_quota_or_unrelated_evidence_never_allows_fallback(cloud_case, reason: str) -> None:
    if reason == "code":
        cloud_case["annotations"] = [{"message": "AssertionError: expected 1 got 2"}]
    elif reason == "foreign_head":
        cloud_case["runs"][0]["head_sha"] = "0" * 40
    elif reason == "foreign_pr":
        cloud_case["pr"]["headRefOid"] = "0" * 40
    elif reason == "missing":
        cloud_case["checks"].clear()
    elif reason == "external_app":
        cloud_case["runs"][0]["app"]["slug"] = "third-party"
    else:
        cloud_case["checks"].append({"name": "build", "state": "FAILURE", "link": "https://github.com/example/repo/runs/9"})
        cloud_case["required"].append(cloud_case["checks"][-1])
    with pytest.raises(SystemExit):
        record(cloud_case, "ai-quality-gate=" + python_command("raise AssertionError('must not run')"))
    state = read_state(cloud_case["root"])
    assert not validation.cloud_is_current(state, cloud_case["root"], cloud_case["workspace"])


def test_changed_workspace_invalidates_local_pass(cloud_case) -> None:
    assert record(cloud_case, "ai-quality-gate=" + python_command("print('ok')")) == 0
    (cloud_case["workspace"] / "app.txt").write_text("modified after validation")
    assert not validation.cloud_is_current(read_state(cloud_case["root"]), cloud_case["root"], cloud_case["workspace"])


def test_test_command_cannot_change_workspace_and_still_pass(cloud_case) -> None:
    command = python_command("from pathlib import Path; Path('app.txt').write_text('modified during validation')")
    assert record(cloud_case, "ai-quality-gate=" + command) == 1
    assert read_state(cloud_case["root"])["github_actions"]["status"] == "local_fallback_failed"


def test_normal_cloud_success_still_uses_cloud_path(cloud_case) -> None:
    cloud_case["checks"][0]["state"] = "SUCCESS"
    assert record(cloud_case, status="passed") == 0
    assert read_state(cloud_case["root"])["github_actions"]["status"] == "passed"


@pytest.mark.parametrize("exit_code", [0, 1, 8])
def test_gh_checks_json_is_readable_when_failed_or_pending(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exit_code: int) -> None:
    monkeypatch.setattr(validation.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, exit_code, "[]", ""))
    assert validation.run_gh_json(tmp_path, "gh", ["pr", "checks", "--json", "name,state,link"]) == []


def test_no_repository_required_checks_is_an_empty_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(validation.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, "", "no required checks reported on the 'codex/test' branch\n"))
    assert validation.run_gh_json(tmp_path, "gh", ["pr", "checks", "--required", "--json", "name,state,link"]) == []


def test_github_details_link_can_identify_the_quota_check(cloud_case) -> None:
    cloud_case["runs"][0]["details_url"] = cloud_case["checks"][0]["link"]
    cloud_case["runs"][0]["html_url"] = "https://github.com/example/repo/runs/another-format"
    assert record(cloud_case, "ai-quality-gate=" + python_command("print('ok')")) == 0


def test_legacy_active_loop_adopts_saved_choice(cloud_case) -> None:
    config_path = cloud_case["workspace"].parent / "config.json"
    config_path.write_text(json.dumps({"ci_quota_policy": "local_fallback"}))
    state = read_state(cloud_case["root"])
    state["config"].pop("ci_quota_policy")
    state["config"]["path"] = str(config_path)
    write_state(cloud_case["root"], state)
    assert record(cloud_case, "ai-quality-gate=" + python_command("print('ok')")) == 0
    assert read_state(cloud_case["root"])["config"]["ci_quota_policy"] == "local_fallback"


def test_timeout_stops_child_processes_before_returning(cloud_case) -> None:
    source = "import time; from pathlib import Path; time.sleep(2); Path('late-write.txt').write_text('orphan')"
    separator = " & " if sys.platform == "win32" else "; "
    command = python_command(source) + separator + "echo child finished"
    assert record(cloud_case, "ai-quality-gate=" + command, timeout=1) == 1
    state = read_state(cloud_case["root"])
    assert state["github_actions"]["status"] == "local_fallback_failed"
    time.sleep(2)
    assert not (cloud_case["workspace"] / "late-write.txt").exists()


def test_quota_evidence_survives_archive_relocation(cloud_case) -> None:
    assert record(cloud_case, "ai-quality-gate=" + python_command("print('ok')")) == 0
    state = read_state(cloud_case["root"])
    state["phase"] = "complete"  # Isolate relocation after the separately tested completion gate.
    write_state(cloud_case["root"], state)
    args = build_parser().parse_args(["--root", str(cloud_case["root"]), "archive"])
    assert commands_loop.cmd_archive(args) == 0
    archived = next((cloud_case["root"].parent / "dev-loop-archive").iterdir())
    assert validation.cloud_is_current(read_state(archived), archived, cloud_case["workspace"])
    assert str(cloud_case["root"]) not in (archived / "github-actions.md").read_text()


def test_payment_recovery_rejects_checks_for_a_new_remote_commit(cloud_case) -> None:
    state = read_state(cloud_case["root"])
    state["config"]["ci_quota_policy"] = "wait_for_payment"
    write_state(cloud_case["root"], state)
    assert record(cloud_case) == 1
    args = build_parser().parse_args(["--root", str(cloud_case["root"]), "resolve-blocker", "--reason", "Quota restored"])
    assert commands_loop.cmd_resolve_blocker(args) == 0
    cloud_case["pr"]["headRefOid"] = "f" * 40
    cloud_case["checks"][0]["state"] = "SUCCESS"
    with pytest.raises(SystemExit, match="head SHA"):
        record(cloud_case, status="passed")
    assert not validation.cloud_is_current(read_state(cloud_case["root"]), cloud_case["root"], cloud_case["workspace"])


def test_payment_recovery_still_requires_all_repository_checks(cloud_case) -> None:
    build = {"name": "build", "state": "FAILURE", "link": "https://github.com/example/repo/runs/8"}
    cloud_case["checks"].append(build)
    cloud_case["required"].append(build)
    cloud_case["runs"].append({**cloud_case["runs"][0], "id": 8, "name": "build", "html_url": build["link"]})
    state = read_state(cloud_case["root"])
    state["config"]["ci_quota_policy"] = "wait_for_payment"
    write_state(cloud_case["root"], state)
    assert record(cloud_case) == 1
    args = build_parser().parse_args(["--root", str(cloud_case["root"]), "resolve-blocker", "--reason", "Quota restored"])
    assert commands_loop.cmd_resolve_blocker(args) == 0
    cloud_case["checks"][0]["state"] = "SUCCESS"
    with pytest.raises(SystemExit, match="build"):
        record(cloud_case, status="passed")
    assert not validation.cloud_is_current(read_state(cloud_case["root"]), cloud_case["root"], cloud_case["workspace"])
