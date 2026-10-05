"""CLI regressions for independent issue retry budgets."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys

import pytest

from .legacy_support import (
    MERGE_INTEGRATOR_REVIEW_BODY,
    SCRIPTS_ROOT,
    append_dev_002,
    fail_command,
    init_loop,
    must,
    pass_command,
    record_plan_review,
    record_review,
    run,
    run_bundled_test_gate,
)


HARNESS = SCRIPTS_ROOT / "dev_loop_harness.py"
pytestmark = pytest.mark.integration


@dataclass
class IssueCase:
    workspace: Path
    root: Path

    def command(self, *arguments: str) -> subprocess.CompletedProcess:
        return run([
            sys.executable, str(HARNESS), "--workspace", str(self.workspace),
            "--root", str(self.root), *arguments,
        ])

    def test(self, issue: str | None = None, *, unit: str = "dev-001",
             passed: bool = False, stage: str = "green") -> subprocess.CompletedProcess:
        arguments = ["run-test", "--unit", unit, "--command",
                     pass_command() if passed else fail_command(), "--stage", stage]
        if issue is not None:
            arguments.extend(["--issue", issue])
        if stage == "red":
            arguments.extend(["--expected-failure", "intentional missing behavior"])
        return self.command(*arguments)

    def state(self) -> dict:
        return json.loads((self.root / "loop-state.json").read_text(encoding="utf-8"))

    def write_state(self, state: dict) -> None:
        (self.root / "loop-state.json").write_text(json.dumps(state), encoding="utf-8")

    def resolve(self) -> subprocess.CompletedProcess:
        return self.command("resolve-blocker", "--reason", "Fixed the exhausted issue before retrying.")


@pytest.fixture
def issue_case(workspace_tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CODEX_DEV_LOOP_TEST_MODE", "1")
    monkeypatch.setenv("CODEX_DEV_LOOP_HOME", str(workspace_tmp_path / "home"))

    def create(retries: int = 1, second_unit: bool = False) -> IssueCase:
        config = workspace_tmp_path / "config.json"
        config.write_text(json.dumps({"max_test_retries_per_unit": retries}), encoding="utf-8")
        workspace, root = init_loop(HARNESS, workspace_tmp_path, config_path=config)
        if second_unit:
            append_dev_002(root)
        case = IssueCase(workspace, root)
        assert case.command("set-phase", "plan_review").returncode == 0
        record_plan_review(HARNESS, workspace, root, workspace_tmp_path)
        assert case.command("set-phase", "branch").returncode == 0
        assert case.command("record-branch", "--branch", "codex/test").returncode == 0
        assert case.command("set-phase", "implementation").returncode == 0
        return case

    return create


def assert_allowed(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout


def assert_exhausted(case: IssueCase, result: subprocess.CompletedProcess, issue: str) -> None:
    assert result.returncode != 0, result.stdout
    assert any(issue in blocker and "retry limit" in blocker for blocker in case.state()["blockers"])


def test_interleaved_issues_and_other_issue_success_do_not_share_budget(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test("A"))
    assert_allowed(case.test("B"))
    assert_allowed(case.test("B", passed=True))
    assert_exhausted(case, case.test("A"), "A")
    attempts = case.state()["test_attempts"]["dev-001"]
    assert [attempt["issue_id"] for attempt in attempts] == ["A", "B", "B", "A"]


def test_issue_identity_is_shared_across_units_with_chronological_pass_reset(issue_case) -> None:
    case = issue_case(second_unit=True)
    assert_allowed(case.test("shared", unit="dev-002"))
    assert_allowed(case.test("shared", passed=True))
    assert_allowed(case.test("shared", unit="dev-002"))
    state = case.state()
    for attempts in state["test_attempts"].values():
        for attempt in attempts:
            attempt["recorded_at"] = "2026-01-01T00:00:00+00:00"
    case.write_state(state)
    assert_exhausted(case, case.test("shared"), "shared")


def test_only_own_green_pass_resets_and_red_runs_do_not_change_budget(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test("A"))
    assert_allowed(case.test("A", stage="red"))
    # A red pass is rejected evidence and must not reset the green failures.
    assert case.test("A", passed=True, stage="red").returncode != 0
    assert_exhausted(case, case.test("A"), "A")
    assert_allowed(case.resolve())
    assert_allowed(case.test("A"))
    assert_allowed(case.test("A", passed=True))
    assert_allowed(case.test("A"))
    assert_exhausted(case, case.test("A"), "A")


@pytest.mark.parametrize("retries", [0, 3])
def test_retry_limit_keeps_n_plus_one_failure_semantics(issue_case, retries: int) -> None:
    case = issue_case(retries=retries)
    for _ in range(retries):
        assert_allowed(case.test("A"))
    assert_exhausted(case, case.test("A"), "A")
    before = len(case.state()["test_attempts"]["dev-001"])
    assert case.test("B").returncode != 0
    assert len(case.state()["test_attempts"]["dev-001"]) == before


def test_resolve_resets_exhausted_issue_only(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test("B"))
    assert_allowed(case.test("A"))
    assert_exhausted(case, case.test("A"), "A")
    assert_allowed(case.resolve())
    assert_allowed(case.test("A"))
    assert_exhausted(case, case.test("B"), "B")


def test_unrelated_blocker_resolution_does_not_reset_test_issues(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test("A"))
    state = case.state()
    state["blockers"] = ["quality gate failed"]
    case.write_state(state)
    assert_allowed(case.resolve())
    assert_exhausted(case, case.test("A"), "A")


def test_legacy_per_unit_fallback_survives_migration_without_explicit_id_collision(issue_case) -> None:
    case = issue_case(second_unit=True)
    assert_allowed(case.test())
    state = case.state()
    for attempt in state["test_attempts"]["dev-001"]:
        attempt.pop("issue_id", None)
        attempt.pop("attempt_sequence", None)
    case.write_state(state)
    assert_allowed(case.test("dev-001"))
    assert_allowed(case.test("unit:dev-001"))
    assert_allowed(case.test(unit="dev-002"))
    assert_exhausted(case, case.test(), "dev-001")
    assert_allowed(case.resolve())
    assert_allowed(case.test())
    assert_exhausted(case, case.test(unit="dev-002"), "dev-002")


def test_legacy_global_reset_marker_is_honored(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test())
    state = case.state()
    attempt = state["test_attempts"]["dev-001"][0]
    state["failure_counter_reset_at"] = attempt["recorded_at"]
    attempt.pop("attempt_sequence", None)
    case.write_state(state)
    assert_allowed(case.test())
    assert_exhausted(case, case.test(), "dev-001")


def test_scoped_reset_does_not_hide_failures_after_backtracking_clears_attempts(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test("A"))
    assert_exhausted(case, case.test("A"), "A")
    assert_allowed(case.resolve())
    assert_allowed(case.test("A", passed=True))
    assert_allowed(case.command("record-spec-merge"))
    assert_allowed(case.command("set-phase", "implementation_review"))
    assert_allowed(case.command("set-phase", "implementation"))
    assert case.state()["test_attempts"] == {}
    assert_allowed(case.test("A"))
    assert_exhausted(case, case.test("A"), "A")


def test_adopted_legacy_pass_resets_fallback_after_sequenced_failure(issue_case) -> None:
    case = issue_case()
    assert_allowed(case.test())
    meta_path = run_bundled_test_gate("dev-001", pass_command(), case.workspace)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    fingerprint = json.loads(case.command("fingerprint", "--json").stdout)["workspace_fingerprint"]
    ledger = case.workspace / ".codex" / "evidence" / "tdd" / "ledger.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"attempts": {"dev-001": [{
        "stage": "green", "status": "passed", "exit_code": 0,
        "command": meta["command"], "log": meta["log_path"], "meta": str(meta_path),
        "workspace_fingerprint": fingerprint,
    }]}}), encoding="utf-8")
    assert_allowed(case.command("adopt-evidence"))
    assert case.state()["test_attempts"]["dev-001"][-1]["adopted_from"] == "standalone"
    assert_allowed(case.test())
    assert_exhausted(case, case.test(), "dev-001")


@pytest.mark.parametrize("issue", ["", "   ", "two\nlines"])
def test_invalid_explicit_issue_is_rejected_before_running(issue_case, issue: str) -> None:
    case = issue_case()
    result = case.test(issue)
    assert result.returncode != 0
    assert "issue" in result.stdout.lower()
    assert case.state()["test_attempts"] == {}


def test_worktree_import_keeps_issue_and_verify_reuses_selected_issue(issue_case, workspace_tmp_path: Path) -> None:
    case = issue_case()
    worktree = workspace_tmp_path / "worktree"
    must(["git", "worktree", "add", "-b", "codex/worktree-issue", str(worktree)], case.workspace)

    def imported(issue: str, passed: bool = False) -> subprocess.CompletedProcess:
        meta = run_bundled_test_gate("dev-001", pass_command() if passed else fail_command(), worktree)
        return case.command("record-test", "--unit", "dev-001", "--issue", issue,
                            "--meta", str(meta), "--worktree", str(worktree))

    assert_allowed(imported("A"))
    assert_allowed(imported("B"))
    assert_exhausted(case, imported("A"), "A")
    assert_allowed(case.resolve())
    assert_allowed(imported("B", passed=True))
    assert_allowed(case.test("later-red", stage="red"))
    review = record_review(HARNESS, case.workspace, case.root, workspace_tmp_path,
                           "merge-integrator", MERGE_INTEGRATOR_REVIEW_BODY)
    assert_allowed(review)
    assert_allowed(case.command("verify-units"))
    latest = case.state()["test_attempts"]["dev-001"][-1]
    assert latest["issue_id"] == "B"
    assert "worktree" not in latest
