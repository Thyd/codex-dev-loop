"""Phase prerequisites and review, quality, PR, and cloud validation."""

from __future__ import annotations
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from .contracts import CORE_VERSION, EVIDENCE_SCHEMA_VERSION
from .evidence import (
    EvidenceContractError,
    load_evidence_document,
    normalize_evidence_document,
    write_evidence_document,
)

from .settings import (
    ACCEPTANCE_HEADINGS,
    AI_REVIEW_CHECK_ALIASES,
    BACKTRACKS,
    CORE_ARTIFACTS,
    DOCS_IMPACT_REVIEWER_ROLE,
    EXPECTED_FAILURE_STOP_WORDS,
    FINAL_ARTIFACTS,
    GOAL_HEADINGS,
    MERGE_INTEGRATOR_ROLE,
    PHASE_INDEX,
    RED_FAILURE_INFRA_PATTERNS,
    RED_FAILURE_SNAPSHOT_PATTERNS,
    REQUIREMENTS_REVIEWER_ROLE,
    REVIEW_SECTIONS,
    SCANNER_CHECK_ALIASES,
    loop_config,
    loop_scale,
)
from .workspace import (
    all_planned_tests_passed,
    assert_no_blockers,
    assert_small_scale_skip_allowed,
    current_git_head,
    current_record,
    has_worktree_evidence,
    is_git_repo,
    missing_or_failing_units,
    parse_report_field,
    phase,
    plan_fingerprint,
    planned_units,
    pr_repository,
    review_decision_allows_progress,
    source_fingerprint,
    unit_tdd_mode,
    workspace_fingerprint,
)
from .specs import (
    load_spec_delta,
)

def assert_phase(state: dict, allowed: set[str]) -> None:
    current = phase(state)
    if current not in allowed:
        raise SystemExit(f"Command is not allowed in phase {current!r}; expected one of {sorted(allowed)}")


def artifact_exists(root: Path, name: str) -> bool:
    return (root / name).exists()


def section_has_content(text: str, heading: str) -> bool:
    marker = next((index for index, line in enumerate(text.splitlines()) if line.strip() == heading), -1)
    if marker < 0:
        return False
    lines = text.splitlines()[marker + 1 :]
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if stripped and stripped not in {"-", "- ...", "TBD", "TODO", "N/A"}:
            return True
    return False


def any_section_has_content(text: str, headings: tuple[str, ...]) -> bool:
    return any(section_has_content(text, heading) for heading in headings)


def assert_source_ready(root: Path) -> None:
    source_path = root / "source.md"
    if not source_path.exists():
        raise SystemExit("Missing source.md; run init first.")
    source = source_path.read_text(encoding="utf-8", errors="replace")
    if not any_section_has_content(source, GOAL_HEADINGS) or not any_section_has_content(source, ACCEPTANCE_HEADINGS):
        raise SystemExit(
            "source.md must contain non-empty Goal and Acceptance Criteria sections. "
            "Stay in the intake phase and clarify the requirement with the user "
            "(record questions and answers in clarification-log.md) before set-phase planning."
        )


ARTIFACT_SECTION_REQUIREMENTS = {
    "technical-design.md": [
        "## Goal", "## Acceptance Criteria", "## Proposed Approach", "## File And Module Scope",
        "## Data Model Or API Changes", "## Dependencies", "## Non-Goals", "## Open Questions",
    ],
    "test-plan.md": [
        "## Unit Tests", "## Integration Tests", "## E2E Or Browser Tests", "## Static Gates",
        "## Manual Checks", "## Coverage Gaps",
    ],
    "risk-analysis.md": [
        "## Correctness Risks", "## Security Risks", "## Data Or Migration Risks", "## Architecture Risks",
        "## Compatibility Risks", "## External Service Or Credential Risks", "## Mitigations",
    ],
    "development-plan.md": [
        "## Unit dev-001", "- Objective:", "- Scope:", "- Acceptance:", "- Test gate:",
        "- TDD:", "- Dependencies:", "- Status:", "- Evidence:",
    ],
}


SCALE_CONTENT_REQUIRED = {
    "small": {"technical-design.md"},
    "standard": {"technical-design.md", "test-plan.md", "risk-analysis.md"},
    "large": {"technical-design.md", "test-plan.md", "risk-analysis.md"},
}


def assert_core_artifacts(root: Path, scale: str = "standard") -> None:
    missing = [name for name in CORE_ARTIFACTS if not artifact_exists(root, name)]
    if missing:
        raise SystemExit("Missing required planning artifacts: " + ", ".join(missing))
    assert_source_ready(root)
    content_required = SCALE_CONTENT_REQUIRED[scale]
    for name, headings in ARTIFACT_SECTION_REQUIREMENTS.items():
        text = (root / name).read_text(encoding="utf-8", errors="replace")
        for heading in headings:
            if heading not in text:
                raise SystemExit(f"{name} missing required section or field: {heading}")
        if name == "development-plan.md":
            continue
        section_headings = [heading for heading in headings if heading.startswith("##")]
        if name in content_required:
            if scale == "large":
                empty = [heading for heading in section_headings if not section_has_content(text, heading)]
                if empty:
                    raise SystemExit(f"{name} must fill every required section at large scale; empty: {', '.join(empty)}")
            elif not any(section_has_content(text, heading) for heading in section_headings):
                raise SystemExit(f"{name} must contain non-placeholder planning content.")
    load_spec_delta(root)
    for unit in planned_units(root):
        unit_tdd_mode(root, unit)


def assert_pr_artifacts(root: Path) -> None:
    missing = [name for name in FINAL_ARTIFACTS if not artifact_exists(root, name)]
    if missing:
        raise SystemExit("Missing required PR artifacts: " + ", ".join(missing))


def clear_downstream_state(state: dict, target: str) -> None:
    if target in {"intake", "planning", "plan_review"}:
        preserved_requirements_review = None
        if target != "intake":
            preserved_requirements_review = state.get("reviews", {}).get(REQUIREMENTS_REVIEWER_ROLE)
        state["reviews"] = {}
        if preserved_requirements_review:
            state["reviews"][REQUIREMENTS_REVIEWER_ROLE] = preserved_requirements_review
        state["test_attempts"] = {}
        state["quality_gate"] = {}
        state["git"] = {}
        state["github_actions"] = {}
        state["blockers"] = []
        state.pop("spec_merge", None)
        return
    if target == "branch":
        state.get("reviews", {}).pop(MERGE_INTEGRATOR_ROLE, None)
        state.get("reviews", {}).pop("implementation-reviewer", None)
        state.get("reviews", {}).pop(DOCS_IMPACT_REVIEWER_ROLE, None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["test_attempts"] = {}
        state["quality_gate"] = {}
        state["git"] = {}
        state["github_actions"] = {}
        state["blockers"] = []
        state.pop("spec_merge", None)
        return
    if target == "implementation":
        state.get("reviews", {}).pop(MERGE_INTEGRATOR_ROLE, None)
        state.get("reviews", {}).pop("implementation-reviewer", None)
        state.get("reviews", {}).pop(DOCS_IMPACT_REVIEWER_ROLE, None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["test_attempts"] = {}
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", ""), "base_commit": git.get("base_commit", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        state.pop("spec_merge", None)
        return
    if target == "implementation_review":
        state.get("reviews", {}).pop("implementation-reviewer", None)
        state.get("reviews", {}).pop(DOCS_IMPACT_REVIEWER_ROLE, None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", ""), "base_commit": git.get("base_commit", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "risk_review":
        state.get("reviews", {}).pop(DOCS_IMPACT_REVIEWER_ROLE, None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", ""), "base_commit": git.get("base_commit", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "quality_gate":
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", ""), "base_commit": git.get("base_commit", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "pr":
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", ""), "base_commit": git.get("base_commit", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "cloud_checks":
        state["github_actions"] = {}
        state["blockers"] = []


def review_is_current(state: dict, role: str, root: Path, workspace: Path) -> bool:
    record = state.get("reviews", {}).get(role, {})
    if not review_decision_allows_progress(role, record.get("decision", "")):
        return False
    if role == REQUIREMENTS_REVIEWER_ROLE:
        return record.get("source_fingerprint") == source_fingerprint(root)
    return current_record(record, root, workspace, include_workspace=role != "plan-reviewer")


def spec_merge_is_current(state: dict, root: Path, workspace: Path) -> bool:
    record = state.get("spec_merge") or {}
    if record.get("status") not in {"merged", "no-impact"}:
        return False
    return current_record(record, root, workspace, include_workspace=True)


def quality_is_current(state: dict, root: Path, workspace: Path) -> bool:
    record = state.get("quality_gate", {})
    if record.get("status") != "passed":
        return False
    return current_record(record, root, workspace, include_workspace=True)


def git_pr_is_current(state: dict, root: Path, workspace: Path) -> bool:
    record = state.get("git", {})
    if not record.get("commit") or not record.get("pr_url"):
        return False
    return current_record(record, root, workspace, include_workspace=True)


def git_commit_is_current(state: dict, root: Path, workspace: Path) -> bool:
    record = state.get("git", {})
    commit = record.get("commit")
    if not commit or not is_git_repo(workspace):
        return False
    if current_git_head(workspace) != commit:
        return False
    return current_record(record, root, workspace, include_workspace=True)


def cloud_is_current(state: dict, root: Path, workspace: Path) -> bool:
    record = state.get("github_actions", {})
    if record.get("status") != "passed":
        return False
    return current_record(record, root, workspace, include_workspace=True)


def assert_completion_prereqs(root: Path, state: dict, workspace: Path) -> None:
    assert_no_blockers(state)
    assert_core_artifacts(root, loop_scale(state))
    if not review_is_current(state, REQUIREMENTS_REVIEWER_ROLE, root, workspace):
        raise SystemExit("Cannot complete before requirements-reviewer passes for the current source.md.")
    automation_level = loop_config(state)["automation_level"]
    if automation_level == "planning_only":
        if not review_is_current(state, "plan-reviewer", root, workspace):
            raise SystemExit("Cannot complete planning-only mode before plan-reviewer passes.")
        return
    if automation_level == "commit_only":
        if not quality_is_current(state, root, workspace):
            raise SystemExit("Cannot complete commit-only mode before quality gate passes.")
        if not git_commit_is_current(state, root, workspace):
            raise SystemExit("Cannot complete commit-only mode before recording the current commit.")
        return
    if not cloud_is_current(state, root, workspace):
        raise SystemExit("Cannot complete before GitHub Actions cloud checks pass.")


def assert_phase_prereqs(root: Path, state: dict, target: str, workspace: Path) -> None:
    if target == "complete":
        assert_completion_prereqs(root, state, workspace)
        return
    assert_no_blockers(state)
    scale = loop_scale(state)
    if target in {"planning", "plan_review", "branch", "implementation", "implementation_review", "risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        assert_source_ready(root)
        if not review_is_current(state, REQUIREMENTS_REVIEWER_ROLE, root, workspace):
            raise SystemExit("Cannot advance before requirements-reviewer passes for the current source.md.")
    if target in {"plan_review", "branch", "implementation", "implementation_review", "risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        assert_core_artifacts(root, scale)
    if target in {"branch", "implementation", "implementation_review", "risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        if not review_is_current(state, "plan-reviewer", root, workspace):
            raise SystemExit("Cannot advance before plan-reviewer passes.")
    if target in {"implementation"}:
        if not state.get("git", {}).get("branch"):
            raise SystemExit("Cannot enter implementation before recording a branch.")
    if target in {"implementation_review", "risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        if not state.get("git", {}).get("branch"):
            raise SystemExit("Missing recorded branch.")
        if not all_planned_tests_passed(root, state, workspace):
            missing = ", ".join(missing_or_failing_units(root, state, workspace))
            raise SystemExit(f"Cannot advance before all planned units have latest test gate passed: {missing}")
        if not spec_merge_is_current(state, root, workspace):
            raise SystemExit(
                "Cannot advance before the spec baseline is reconciled with spec-delta.md; "
                "merge the delta into the spec directory and run record-spec-merge."
            )
        if has_worktree_evidence(state) and not review_is_current(state, MERGE_INTEGRATOR_ROLE, root, workspace):
            raise SystemExit("Cannot advance after parallel worktree merges before merge-integrator passes for the current merged tree.")
    if target in {"risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot advance before implementation-reviewer passes.")
    if target in {"quality_gate", "pr", "cloud_checks", "complete"}:
        if not review_is_current(state, "risk-reviewer", root, workspace):
            if scale == "small":
                assert_small_scale_skip_allowed(state, workspace)
            else:
                raise SystemExit("Cannot advance before risk-reviewer passes.")
        if not review_is_current(state, DOCS_IMPACT_REVIEWER_ROLE, root, workspace):
            raise SystemExit("Cannot advance to quality gate before docs-impact-reviewer returns no-docs-needed for the current workspace.")
    if target in {"pr", "cloud_checks", "complete"}:
        if not quality_is_current(state, root, workspace):
            raise SystemExit("Cannot advance before quality gate passes.")
        assert_pr_artifacts(root)
    if target in {"cloud_checks", "complete"}:
        if not state.get("git", {}).get("commit") or not state.get("git", {}).get("pr_url"):
            raise SystemExit("Cannot advance before branch commit and PR URL are recorded.")
        if not git_pr_is_current(state, root, workspace):
            raise SystemExit("Recorded PR is stale for the current plan or workspace.")
    if target == "complete":
        if not cloud_is_current(state, root, workspace):
            raise SystemExit("Cannot complete before GitHub Actions cloud checks pass.")


def assert_transition(root: Path, state: dict, target: str, workspace: Path) -> None:
    current = phase(state)
    if current not in PHASE_INDEX:
        raise SystemExit(f"Current phase is invalid: {current}")
    if target not in PHASE_INDEX:
        raise SystemExit(f"Unknown phase: {target}")
    current_index = PHASE_INDEX[current]
    target_index = PHASE_INDEX[target]
    if target == current:
        assert_phase_prereqs(root, state, target, workspace)
        return
    if target == "complete":
        assert_phase_prereqs(root, state, target, workspace)
        return
    if target_index == current_index + 1 or (current, target) in BACKTRACKS:
        assert_phase_prereqs(root, state, target, workspace)
        return
    if current == "implementation_review" and target == "quality_gate" and loop_scale(state) == "small":
        # Small scale may skip the risk_review phase; the prereqs re-check the
        # sensitive-path guard so the shortcut closes as soon as risky files change.
        assert_phase_prereqs(root, state, target, workspace)
        return
    raise SystemExit(f"Illegal phase transition: {current} -> {target}")


def parse_decision(report: Path) -> str:
    text = report.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip().lower()
        if line.startswith("decision:"):
            return line.split(":", 1)[1].strip()
    return ""


def validate_review_report(role: str, report: Path, agent_id: str, root: Path, workspace: Path) -> None:
    text = report.read_text(encoding="utf-8", errors="replace")
    missing = [section for section in REVIEW_SECTIONS[role] if section.lower() not in text.lower()]
    if missing:
        raise SystemExit(f"{role} report is missing required sections: {', '.join(missing)}")
    empty = [section for section in REVIEW_SECTIONS[role] if section != "Docs Impact" and not report_section_has_content(text, section)]
    if empty:
        raise SystemExit(f"{role} report has empty required sections: {', '.join(empty)}")
    report_agent = parse_report_field(text, "Agent ID:")
    if report_agent != agent_id:
        raise SystemExit(f"{role} report Agent ID does not match --agent-id.")
    if role == REQUIREMENTS_REVIEWER_ROLE:
        report_source = parse_report_field(text, "Source Fingerprint:")
        if report_source != source_fingerprint(root):
            raise SystemExit(f"{role} report source fingerprint is stale or missing.")
        return
    report_plan = parse_report_field(text, "Plan Fingerprint:")
    report_workspace = parse_report_field(text, "Workspace Fingerprint:")
    if report_plan != plan_fingerprint(root):
        raise SystemExit(f"{role} report plan fingerprint is stale or missing.")
    if role != "plan-reviewer" and report_workspace != workspace_fingerprint(workspace):
        raise SystemExit(f"{role} report workspace fingerprint is stale or missing.")


def validate_agent_id(agent_id: str) -> None:
    if not agent_id.strip():
        raise SystemExit("Subagent review records require --agent-id.")
    if len(agent_id.strip()) < 12:
        raise SystemExit("Subagent agent id is too short to be useful as provenance.")


def report_section_has_content(text: str, section: str) -> bool:
    """Require reviewer sections to contain evidence, not just template labels."""
    target = section.strip().strip(":").lower()
    lines = text.splitlines()
    start = -1
    for index, raw in enumerate(lines):
        normalized = raw.strip().lstrip("#").strip().strip(":").lower()
        if normalized == target:
            start = index
            break
    if start < 0:
        return False
    known = {
        item.strip().strip(":").lower()
        for values in REVIEW_SECTIONS.values()
        for item in values
    }
    for raw in lines[start + 1 :]:
        stripped = raw.strip()
        normalized = stripped.lstrip("#").strip().strip(":").lower()
        if normalized in known or stripped.lower().startswith(("agent id:", "source fingerprint:", "plan fingerprint:", "workspace fingerprint:", "decision:")):
            break
        if stripped and stripped not in {"-", "- ...", "...", "TBD", "TODO"}:
            return True
    return False


def expected_failure_matches(log_text: str, expected: str) -> bool:
    expected = expected.strip().lower()
    if not expected:
        return True
    haystack = log_text.lower()
    if expected in haystack:
        return True
    tokens = [
        token
        for token in re.findall(r"[\w.-]{3,}", expected, flags=re.UNICODE)
        if token not in EXPECTED_FAILURE_STOP_WORDS
    ]
    if not tokens:
        return False
    matches = sum(1 for token in tokens if token in haystack)
    required = max(1, (len(tokens) + 1) // 2)
    return matches >= required


def validate_red_failure(unit: str, log_path: Path, expected: str = "", status: str = "failed") -> dict:
    expected = expected.strip()
    if not expected:
        return {
            "status": "invalid",
            "reason": "red-stage evidence requires a declared expected failure reason.",
            "expected": expected,
        }
    if status == "passed":
        return {
            "status": "invalid",
            "reason": "red-stage test passed before implementation; the planned missing behavior may already exist or the test is too weak.",
            "expected": expected,
        }
    if status != "failed":
        return {
            "status": "invalid",
            "reason": f"red-stage run ended with {status}; fix the test harness so the red run fails cleanly.",
            "expected": expected,
        }
    if not log_path.exists():
        return {"status": "invalid", "reason": f"red-stage log does not exist: {log_path}", "expected": expected}
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    lower = log_text.lower()
    for reason, patterns in RED_FAILURE_INFRA_PATTERNS:
        matched = all(pattern in lower for pattern in patterns) if reason == "missing fixture" else any(pattern in lower for pattern in patterns)
        if matched:
            return {
                "status": "invalid",
                "reason": f"red-stage failed because of {reason}, not the target behavior.",
                "expected": expected,
            }
    if any(pattern in lower for pattern in RED_FAILURE_SNAPSHOT_PATTERNS):
        return {
            "status": "needs-human-review",
            "reason": "red-stage failure appears to involve snapshot drift; confirm this is the intended missing behavior before recording red evidence.",
            "expected": expected,
        }
    if expected and not expected_failure_matches(log_text, expected):
        return {
            "status": "invalid",
            "reason": "red-stage failure log does not match the declared expected failure reason.",
            "expected": expected,
        }
    reason = "red-stage failed for the declared expected reason." if expected else "red-stage failure passed built-in infrastructure-error screening."
    return {"status": "pass", "reason": reason, "expected": expected}


def load_test_meta(meta_path: Path, unit: str, workspace: Path) -> dict:
    if not meta_path.exists():
        raise SystemExit(f"Test gate metadata does not exist: {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Test gate metadata is not valid JSON: {exc}") from exc
    if meta.get("unit") != unit:
        raise SystemExit(f"Test gate metadata unit {meta.get('unit')!r} does not match {unit!r}.")
    status = meta.get("status")
    if status not in {"passed", "failed", "timeout", "error"}:
        raise SystemExit(f"Invalid test gate status in metadata: {status!r}")
    command = str(meta.get("command") or "").strip()
    if not command:
        raise SystemExit("Test gate metadata must include the executed command.")
    log_path = Path(str(meta.get("log_path") or ""))
    if not log_path.exists():
        raise SystemExit(f"Test gate log path does not exist: {log_path}")
    cwd = Path(str(meta.get("cwd") or ".")).resolve()
    if cwd != workspace.resolve():
        raise SystemExit(f"Test gate cwd {cwd} does not match workspace {workspace.resolve()}.")
    exit_code = meta.get("exit_code")
    if status == "passed" and exit_code != 0:
        raise SystemExit("Passed test gate metadata must have exit_code 0.")
    if status != "passed" and exit_code == 0:
        raise SystemExit("Failed test gate metadata must not have exit_code 0.")
    return meta


def parse_quality_decision(summary: Path) -> str:
    text = summary.read_text(encoding="utf-8", errors="replace")
    if "# AI Quality Gate Summary" not in text:
        raise SystemExit("Quality summary must be produced by ai-code-quality-gate.")
    for raw_line in text.splitlines():
        line = raw_line.strip().lower()
        if line.startswith("- decision:"):
            return line.split(":", 1)[1].strip(" `")
    raise SystemExit("Quality summary is missing a Decision line.")


def validate_quality_results(results_path: Path, required_gates: list[str], require_passed: bool = True) -> list[dict]:
    if not results_path.exists():
        raise SystemExit(f"Quality gate results JSON does not exist: {results_path}")
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Quality gate results JSON is invalid: {exc}") from exc
    if not isinstance(results, list):
        raise SystemExit("Quality gate results JSON must be a list.")
    by_gate: dict[str, dict] = {}
    for item in results:
        if not isinstance(item, dict) or "gate" not in item or "status" not in item:
            raise SystemExit("Quality gate results JSON contains invalid gate records.")
        by_gate[str(item["gate"])] = item
    if require_passed:
        missing = [gate for gate in required_gates if gate not in by_gate]
        if missing:
            raise SystemExit("Quality gate results are missing required gates: " + ", ".join(missing))
        failed: list[str] = []
        for gate in required_gates:
            item = by_gate[gate]
            if item.get("status") != "passed" or item.get("exit_code") != 0:
                failed.append(f"{gate}={item.get('status')}/{item.get('exit_code')}")
            command = str(item.get("command") or "").strip()
            if not command:
                failed.append(f"{gate}=missing-command")
            log_path = str(item.get("log_path") or "").strip()
            if not log_path or not Path(log_path).exists():
                failed.append(f"{gate}=missing-log")
        if failed:
            raise SystemExit("Quality gate results are not passing: " + ", ".join(failed))
    return results


def quality_decision_allows_progress(decision: str, results: list[dict], required_gates: list[str]) -> tuple[bool, list[str]]:
    if decision == "pass":
        return True, []
    if decision != "needs-human-review":
        return False, []
    required = set(required_gates)
    skipped_review_gates = [
        str(item.get("gate") or "")
        for item in results
        if str(item.get("gate") or "") in {"subagent-alignment", "ai-review"} and str(item.get("status") or "") == "skipped"
    ]
    deferred = [gate for gate in skipped_review_gates if gate == "ai-review" and gate not in required]
    if skipped_review_gates and sorted(skipped_review_gates) == sorted(deferred):
        return True, deferred
    return False, deferred


def passing_check(item: dict) -> bool:
    state = str(item.get("state") or item.get("status") or "").strip().lower()
    conclusion = str(item.get("conclusion") or item.get("outcome") or "").strip().lower()
    if conclusion:
        return conclusion in {"pass", "passed", "success", "successful"}
    return state in {"pass", "passed", "success", "successful", "completed_successfully"}


def canonical_check_name(value: str) -> str:
    normalized = value.strip().lower()
    return "-".join(part for part in normalized.replace("_", "-").replace("/", " ").split() if part)


def is_ai_review_check(name: str) -> bool:
    canonical = canonical_check_name(name)
    return any(alias in canonical for alias in AI_REVIEW_CHECK_ALIASES)


def check_satisfies_required(check_name: str, required: str) -> bool:
    canonical = canonical_check_name(check_name)
    required_canonical = canonical_check_name(required)
    if canonical == required_canonical:
        return True
    aliases = SCANNER_CHECK_ALIASES.get(required_canonical, [])
    if not aliases:
        return False
    tokens = set(canonical.split("-"))
    return any(alias in tokens for alias in aliases)


def matching_required_checks(checks: list[dict], required: str) -> list[dict]:
    return [item for item in checks if check_satisfies_required(item["name"], required)]


def run_gh_json(workspace: Path, gh: str, args: list[str]) -> object:
    # Keep stderr separate: gh writes notices, update hints, and progress to
    # stderr, and merging streams would corrupt the JSON on stdout.
    result = subprocess.run(
        [gh, *args],
        cwd=str(workspace),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"{gh} {' '.join(args)} failed"
        raise SystemExit(message)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"GitHub CLI did not return valid JSON: {exc}") from exc


def load_json_file(path: Path) -> object:
    if not path.exists():
        raise SystemExit(f"Evidence file does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Evidence file is not valid JSON: {path}: {exc}") from exc


def validate_pr_evidence(data: object, branch: str, commit: str, pr_url: str, expected_repo: str) -> dict:
    if not isinstance(data, dict):
        raise SystemExit("PR evidence must be a JSON object.")
    if data.get("url") != pr_url:
        raise SystemExit("GitHub PR evidence URL does not match.")
    if data.get("headRefName") != branch:
        raise SystemExit("GitHub PR evidence branch does not match.")
    if data.get("headRefOid") != commit:
        raise SystemExit("GitHub PR evidence head SHA does not match commit.")
    if str(data.get("state") or "").upper() != "OPEN":
        raise SystemExit("GitHub PR evidence must show an open PR.")
    actual_repo = pr_repository(data, pr_url)
    if not expected_repo:
        raise SystemExit("Could not determine local GitHub origin repository.")
    if actual_repo != expected_repo:
        raise SystemExit(f"GitHub PR evidence repository {actual_repo!r} does not match local origin {expected_repo!r}.")
    return data


def validate_cloud_evidence(data: object, required_checks: list[str], require_ai_review: bool = True) -> list[dict]:
    if not isinstance(data, list):
        raise SystemExit("GitHub Actions evidence must be a JSON list.")
    checks: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            raise SystemExit("GitHub Actions evidence contains a non-object check.")
        name = str(item.get("name") or item.get("checkName") or "")
        state = str(item.get("state") or item.get("status") or "")
        if not name:
            raise SystemExit("GitHub Actions evidence contains a check without a name.")
        checks.append({"name": name, "state": state, **item})
    matched: dict[str, list[dict]] = {check: matching_required_checks(checks, check) for check in required_checks}
    missing = [check for check, items in matched.items() if not items]
    if missing:
        raise SystemExit("GitHub Actions evidence is missing required checks: " + ", ".join(missing))
    ai_review_checks = [item for item in checks if is_ai_review_check(item["name"])]
    if require_ai_review and not ai_review_checks:
        raise SystemExit("GitHub Actions evidence must include Qodo PR-Agent, CodeRabbit, or another AI review check.")
    must_pass: list[dict] = []
    for items in matched.values():
        for item in items:
            if item not in must_pass:
                must_pass.append(item)
    must_pass.extend(item for item in ai_review_checks if item not in must_pass)
    failing = sorted({item["name"] for item in must_pass if not passing_check(item)})
    if failing:
        raise SystemExit("GitHub Actions checks are not all passing: " + ", ".join(failing))
    return checks


def copy_report(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest.resolve():
        return
    shutil.copyfile(src, dest)
