#!/usr/bin/env python3
"""State helper for the Codex dev loop.

This does not replace Codex as the harness. It provides a small enforceable
state ledger that Codex can call while running the loop.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse


PHASES = [
    "intake",
    "planning",
    "plan_review",
    "branch",
    "implementation",
    "implementation_review",
    "risk_review",
    "quality_gate",
    "pr",
    "cloud_checks",
    "complete",
]

REVIEW_ROLES = {"plan-reviewer", "implementation-reviewer", "risk-reviewer"}
PROTECTED_BRANCHES = {"main", "master", "develop"}
CORE_ARTIFACTS = ["source.md", "technical-design.md", "test-plan.md", "risk-analysis.md", "development-plan.md", "decision-log.md"]
FINAL_ARTIFACTS = ["final-report.md", "pr-body.md", "quality-gate-summary.md"]
REQUIRED_CLOUD_CHECKS = ["ai-quality-gate", "semgrep", "codeql", "sonar", "qodana", "subagent-alignment"]
AI_REVIEW_CHECK_ALIASES = ["qodo", "coderabbit", "pr-agent", "ai-review"]
REQUIRED_QUALITY_GATES = ["lint", "typecheck", "test", "semgrep", "codeql", "sonar", "qodana", "subagent-alignment"]
DEFAULT_CODEX_HOME = Path.home() / ".codex"
DEFAULT_CONFIG_PATH = DEFAULT_CODEX_HOME / "config" / "codex-dev-loop.json"
DEFAULT_TEST_GATE_SCRIPT = DEFAULT_CODEX_HOME / "skills" / "automated-dev-executor" / "scripts" / "test_gate.py"
DEFAULT_QUALITY_GATE_SCRIPT = DEFAULT_CODEX_HOME / "skills" / "ai-code-quality-gate" / "scripts" / "quality_gate.py"
TEST_MODE_ENV = "CODEX_DEV_LOOP_TEST_MODE"
CONFIG_SCHEMA_VERSION = 1
DEFAULT_CONFIG = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "automation_level": "pr_without_merge",
    "source_types": ["markdown", "notion"],
    "quality_profile": "standard",
    "test_failure_limit": 3,
    "risk_mode": "stop_and_ask",
}
QUALITY_PROFILES = {
    "light": {
        "quality_gates": ["test", "subagent-alignment"],
        "cloud_checks": ["ai-quality-gate"],
        "require_ai_review": False,
        "strict": False,
    },
    "standard": {
        "quality_gates": ["lint", "typecheck", "test", "subagent-alignment"],
        "cloud_checks": ["ai-quality-gate"],
        "require_ai_review": True,
        "strict": False,
    },
    "strict": {
        "quality_gates": ["lint", "typecheck", "test", "semgrep", "codeql", "sonar", "qodana", "subagent-alignment"],
        "cloud_checks": ["ai-quality-gate", "semgrep", "codeql", "sonar", "qodana", "subagent-alignment"],
        "require_ai_review": True,
        "strict": True,
    },
}
AUTOMATION_LEVELS = {"pr_without_merge", "commit_only", "planning_only"}
QUALITY_PROFILE_NAMES = set(QUALITY_PROFILES)
RISK_MODES = {"stop_and_ask", "serious_only", "best_effort"}
SOURCE_TYPES = {"markdown", "notion"}
REVIEW_SECTIONS = {
    "plan-reviewer": ["Findings:", "Required Revisions:", "Blocking Questions:", "Rationale:"],
    "implementation-reviewer": [
        "PR Objective:",
        "Diff Summary:",
        "Requirement Match:",
        "Test Coverage:",
        "Unexpected Changes:",
        "Risk Summary:",
        "Merge Recommendation:",
    ],
    "risk-reviewer": [
        "Architecture Risk:",
        "Security Risk:",
        "Data Or Migration Risk:",
        "Compatibility Risk:",
        "External Service Or Credential Risk:",
        "Required Actions:",
    ],
}
PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}
BACKTRACKS = {
    ("plan_review", "planning"),
    ("implementation_review", "implementation"),
    ("risk_review", "implementation"),
    ("quality_gate", "implementation"),
    ("pr", "implementation"),
    ("cloud_checks", "implementation"),
    ("complete", "implementation"),
}

TEMPLATES = {
    "technical-design.md": "# Technical Design\n\n## Goal\n\n## Acceptance Criteria\n\n## Proposed Approach\n\n## File And Module Scope\n\n## Data Model Or API Changes\n\n## Dependencies\n\n## Non-Goals\n\n## Open Questions\n",
    "test-plan.md": "# Test Plan\n\n## Unit Tests\n\n## Integration Tests\n\n## E2E Or Browser Tests\n\n## Static Gates\n\n## Manual Checks\n\n## Coverage Gaps\n",
    "risk-analysis.md": "# Risk Analysis\n\n## Correctness Risks\n\n## Security Risks\n\n## Data Or Migration Risks\n\n## Architecture Risks\n\n## Compatibility Risks\n\n## External Service Or Credential Risks\n\n## Mitigations\n",
    "development-plan.md": "# Development Plan\n\n## Unit dev-001\n\n- Objective:\n- Scope:\n- Acceptance:\n- Test gate:\n- Dependencies:\n- Status: pending\n- Evidence:\n",
    "decision-log.md": "# Decision Log\n\n",
    "github-actions.md": "# GitHub Actions\n\n## PR\n\n- URL:\n\n## Checks\n\n| Check | Status | URL |\n| --- | --- | --- |\n\n## Decision\n\npending\n\n## Notes\n",
    "final-report.md": "# Final Report\n\n## Summary\n\n## Changed Files\n\n## Test Evidence\n\n## Quality Gate\n\n## Subagent Reviews\n\n## GitHub Actions\n\n## Commit\n\n## Pull Request\n\n## Follow-Ups\n",
    "pr-body.md": "## Summary\n\n## Technical Design\n\n## Tests\n\n## Quality Gate\n\n## Subagent Reviews\n\n## Risk\n\n## Follow-ups\n",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged


def default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def normalize_config(raw: object) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("codex-dev-loop config must be a JSON object.")
    config = default_config()
    config.update(raw)

    if config.get("automation_level") not in AUTOMATION_LEVELS:
        raise SystemExit(f"Invalid automation_level in codex-dev-loop config: {config.get('automation_level')!r}")
    if config.get("quality_profile") not in QUALITY_PROFILE_NAMES:
        raise SystemExit(f"Invalid quality_profile in codex-dev-loop config: {config.get('quality_profile')!r}")
    if config.get("risk_mode") not in RISK_MODES:
        raise SystemExit(f"Invalid risk_mode in codex-dev-loop config: {config.get('risk_mode')!r}")
    if not isinstance(config.get("source_types"), list) or not config["source_types"]:
        raise SystemExit("source_types in codex-dev-loop config must be a non-empty list.")
    invalid_source_types = sorted(set(config["source_types"]) - SOURCE_TYPES)
    if invalid_source_types:
        raise SystemExit("Invalid source_types in codex-dev-loop config: " + ", ".join(invalid_source_types))
    try:
        test_failure_limit = int(config.get("test_failure_limit"))
    except (TypeError, ValueError) as exc:
        raise SystemExit("test_failure_limit in codex-dev-loop config must be an integer.") from exc
    if test_failure_limit not in {0, 1, 2, 3}:
        raise SystemExit("test_failure_limit in codex-dev-loop config must be one of 0, 1, 2, or 3.")
    config["test_failure_limit"] = test_failure_limit
    config["schema_version"] = CONFIG_SCHEMA_VERSION
    return config


def load_loop_config(config_path: str = "") -> dict:
    path_text = config_path or os.environ.get("CODEX_DEV_LOOP_CONFIG", "")
    path = Path(path_text).expanduser() if path_text else DEFAULT_CONFIG_PATH
    if not path.exists():
        config = default_config()
        config["path"] = str(path)
        config["configured"] = False
        return config
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"codex-dev-loop config is invalid JSON: {path}: {exc}") from exc
    config = normalize_config(data)
    config["path"] = str(path)
    config["configured"] = True
    return config


def loop_config(state: dict) -> dict:
    return normalize_config(state.get("config", {}))


def quality_profile(state: dict) -> dict:
    return QUALITY_PROFILES[loop_config(state)["quality_profile"]]


def assert_config_allows_phase(state: dict, target: str) -> None:
    automation_level = loop_config(state)["automation_level"]
    if target == "complete":
        return
    if automation_level == "planning_only" and PHASE_INDEX[target] > PHASE_INDEX["plan_review"]:
        raise SystemExit("Configured automation_level=planning_only blocks implementation, git, PR, and cloud-check phases.")
    if automation_level == "commit_only" and PHASE_INDEX[target] >= PHASE_INDEX["pr"]:
        raise SystemExit("Configured automation_level=commit_only blocks PR and cloud-check phases.")


def read_state(root: Path) -> dict:
    path = root / "loop-state.json"
    if not path.exists():
        raise SystemExit(f"Missing loop state: {path}. Run init first.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    (root / "loop-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def phase(state: dict) -> str:
    return state.get("phase", "")


def has_passed_review(state: dict, role: str) -> bool:
    return state.get("reviews", {}).get(role, {}).get("decision") == "pass"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_files(base: Path, names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in names:
        path = base / name
        digest.update(name.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def plan_fingerprint(root: Path) -> str:
    return hash_files(root, CORE_ARTIFACTS)


def is_excluded_workspace_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    return any(part in {".git", ".codex", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"} for part in parts)


def run_git(workspace: Path, args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    completed = subprocess.run(["git", *args], cwd=str(workspace), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip() or f"git {' '.join(args)} failed")
    return completed


def is_git_repo(workspace: Path) -> bool:
    return run_git(workspace, ["rev-parse", "--is-inside-work-tree"]).stdout.strip() == "true"


def current_git_branch(workspace: Path) -> str:
    return run_git(workspace, ["branch", "--show-current"], check=True).stdout.strip()


def current_git_head(workspace: Path) -> str:
    return run_git(workspace, ["rev-parse", "HEAD"], check=True).stdout.strip()


def git_origin_repository(workspace: Path) -> str:
    remote = run_git(workspace, ["remote", "get-url", "origin"], check=True).stdout.strip()
    return normalize_github_repository(remote)


def normalize_github_repository(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("git@github.com:"):
        path = text.split(":", 1)[1]
    elif text.startswith("ssh://git@github.com/"):
        path = urlparse(text).path.lstrip("/")
    else:
        parsed = urlparse(text)
        if parsed.netloc.lower() != "github.com":
            return ""
        path = parsed.path.lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return ""
    return "/".join(parts[:2]).lower()


def pr_repository(data: dict, pr_url: str) -> str:
    for key in ("repository", "repositoryFullName", "baseRepository"):
        value = data.get(key)
        if isinstance(value, str):
            normalized = normalize_github_repository(f"https://github.com/{value}")
            if normalized:
                return normalized
        if isinstance(value, dict):
            full_name = value.get("nameWithOwner") or value.get("fullName")
            if isinstance(full_name, str):
                normalized = normalize_github_repository(f"https://github.com/{full_name}")
                if normalized:
                    return normalized
    return normalize_github_repository(pr_url)


def workspace_files(workspace: Path) -> list[Path]:
    if is_git_repo(workspace):
        completed = run_git(workspace, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], check=True)
        items = [item for item in completed.stdout.split("\0") if item]
        paths = [workspace / item for item in items if not is_excluded_workspace_path(item)]
        return sorted(paths, key=lambda path: path.relative_to(workspace).as_posix().lower())

    paths: list[Path] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if is_excluded_workspace_path(relative):
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(workspace).as_posix().lower())


def workspace_fingerprint(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in workspace_files(workspace):
        relative = path.relative_to(workspace).as_posix()
        digest.update(relative.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def evidence_fingerprint(root: Path, workspace: Path) -> dict:
    return {"plan": plan_fingerprint(root), "workspace": workspace_fingerprint(workspace)}


def current_record(record: dict, root: Path, workspace: Path, include_workspace: bool) -> bool:
    if record.get("plan_fingerprint") != plan_fingerprint(root):
        return False
    if include_workspace and record.get("workspace_fingerprint") != workspace_fingerprint(workspace):
        return False
    return True


def parse_report_field(text: str, label: str) -> str:
    normalized_label = label.lower()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower().startswith(normalized_label):
            return line.split(":", 1)[1].strip()
    return ""


def run_child(command: list[str], workspace: Path) -> subprocess.CompletedProcess:
    env = {**os.environ}
    return subprocess.run(command, cwd=str(workspace), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


def test_mode_enabled() -> bool:
    return os.environ.get(TEST_MODE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def assert_test_mode(feature: str) -> None:
    if not test_mode_enabled():
        raise SystemExit(f"{feature} is only allowed when {TEST_MODE_ENV}=1.")


def parse_key_value_output(output: str, key: str) -> str:
    prefix = f"{key}="
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def planned_units(root: Path) -> list[str]:
    plan = root / "development-plan.md"
    if not plan.exists():
        return []
    units: list[str] = []
    for raw_line in plan.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.lower().startswith("## unit "):
            unit = line.split(None, 2)[-1].strip()
            if unit and unit not in units:
                units.append(unit)
    return units


def latest_test_status(state: dict, unit: str) -> str:
    attempts = state.get("test_attempts", {}).get(unit, [])
    if not attempts:
        return ""
    return attempts[-1].get("status", "")


def all_planned_tests_passed(root: Path, state: dict, workspace: Path) -> bool:
    units = planned_units(root)
    if not units:
        return False
    for unit in units:
        attempts = state.get("test_attempts", {}).get(unit, [])
        if not attempts:
            return False
        latest = attempts[-1]
        if latest.get("status") != "passed":
            return False
        if not current_record(latest, root, workspace, include_workspace=True):
            return False
    return True


def missing_or_failing_units(root: Path, state: dict, workspace: Path) -> list[str]:
    missing: list[str] = []
    for unit in planned_units(root):
        attempts = state.get("test_attempts", {}).get(unit, [])
        if not attempts:
            missing.append(unit)
            continue
        latest = attempts[-1]
        if latest.get("status") != "passed" or not current_record(latest, root, workspace, include_workspace=True):
            missing.append(unit)
    return missing


def add_blocker(state: dict, message: str) -> None:
    blockers = state.setdefault("blockers", [])
    if message not in blockers:
        blockers.append(message)


def assert_no_blockers(state: dict) -> None:
    blockers = state.get("blockers") or []
    if blockers:
        raise SystemExit("Loop is blocked: " + "; ".join(blockers))


def assert_phase(state: dict, allowed: set[str]) -> None:
    current = phase(state)
    if current not in allowed:
        raise SystemExit(f"Command is not allowed in phase {current!r}; expected one of {sorted(allowed)}")


def artifact_exists(root: Path, name: str) -> bool:
    return (root / name).exists()


def section_has_content(text: str, heading: str) -> bool:
    marker = text.find(heading)
    if marker < 0:
        return False
    lines = text[marker + len(heading) :].splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if stripped and stripped not in {"-", "- ...", "TBD", "TODO", "N/A"}:
            return True
    return False


def assert_core_artifacts(root: Path) -> None:
    missing = [name for name in CORE_ARTIFACTS if not artifact_exists(root, name)]
    if missing:
        raise SystemExit("Missing required planning artifacts: " + ", ".join(missing))
    source = (root / "source.md").read_text(encoding="utf-8", errors="replace")
    if not section_has_content(source, "## Goal") or not section_has_content(source, "## Acceptance Criteria"):
        raise SystemExit("source.md must contain non-empty Goal and Acceptance Criteria sections.")
    required_sections = {
        "technical-design.md": ["## Proposed Approach", "## File And Module Scope"],
        "test-plan.md": ["## Unit Tests", "## Static Gates"],
        "risk-analysis.md": ["## Correctness Risks", "## Architecture Risks"],
        "development-plan.md": ["## Unit dev-001", "- Objective:", "- Test gate:"],
    }
    for name, headings in required_sections.items():
        text = (root / name).read_text(encoding="utf-8", errors="replace")
        for heading in headings:
            if heading not in text:
                raise SystemExit(f"{name} missing required section or field: {heading}")
        if name != "development-plan.md" and not any(section_has_content(text, heading) for heading in headings if heading.startswith("##")):
            raise SystemExit(f"{name} must contain non-placeholder planning content.")


def assert_pr_artifacts(root: Path) -> None:
    missing = [name for name in FINAL_ARTIFACTS if not artifact_exists(root, name)]
    if missing:
        raise SystemExit("Missing required PR artifacts: " + ", ".join(missing))


def clear_downstream_state(state: dict, target: str) -> None:
    if target in {"planning", "plan_review"}:
        state["reviews"] = {}
        state["test_attempts"] = {}
        state["quality_gate"] = {}
        state["git"] = {}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "branch":
        state.get("reviews", {}).pop("implementation-reviewer", None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["test_attempts"] = {}
        state["quality_gate"] = {}
        state["git"] = {}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "implementation":
        state.get("reviews", {}).pop("implementation-reviewer", None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["test_attempts"] = {}
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "implementation_review":
        state.get("reviews", {}).pop("implementation-reviewer", None)
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "risk_review":
        state.get("reviews", {}).pop("risk-reviewer", None)
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "quality_gate":
        state["quality_gate"] = {}
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "pr":
        git = state.get("git", {})
        state["git"] = {"branch": git.get("branch", ""), "branch_recorded_at": git.get("branch_recorded_at", "")}
        state["github_actions"] = {}
        state["blockers"] = []
        return
    if target == "cloud_checks":
        state["github_actions"] = {}
        state["blockers"] = []


def review_is_current(state: dict, role: str, root: Path, workspace: Path) -> bool:
    record = state.get("reviews", {}).get(role, {})
    if record.get("decision") != "pass":
        return False
    return current_record(record, root, workspace, include_workspace=role != "plan-reviewer")


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
    assert_core_artifacts(root)
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
    if target in {"plan_review", "branch", "implementation", "implementation_review", "risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        assert_core_artifacts(root)
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
    if target in {"risk_review", "quality_gate", "pr", "cloud_checks", "complete"}:
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot advance before implementation-reviewer passes.")
    if target in {"quality_gate", "pr", "cloud_checks", "complete"}:
        if not review_is_current(state, "risk-reviewer", root, workspace):
            raise SystemExit("Cannot advance before risk-reviewer passes.")
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
    report_agent = parse_report_field(text, "Agent ID:")
    report_plan = parse_report_field(text, "Plan Fingerprint:")
    report_workspace = parse_report_field(text, "Workspace Fingerprint:")
    if report_agent != agent_id:
        raise SystemExit(f"{role} report Agent ID does not match --agent-id.")
    if report_plan != plan_fingerprint(root):
        raise SystemExit(f"{role} report plan fingerprint is stale or missing.")
    if role != "plan-reviewer" and report_workspace != workspace_fingerprint(workspace):
        raise SystemExit(f"{role} report workspace fingerprint is stale or missing.")


def validate_agent_id(agent_id: str) -> None:
    if not agent_id.strip():
        raise SystemExit("Subagent review records require --agent-id.")
    if len(agent_id.strip()) < 12:
        raise SystemExit("Subagent agent id is too short to be useful as provenance.")


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


def run_gh_json(workspace: Path, gh: str, args: list[str]) -> object:
    result = run_child([gh, *args], workspace)
    if result.returncode != 0:
        raise SystemExit(result.stdout.strip() or f"{gh} {' '.join(args)} failed")
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
    by_canonical_name = {canonical_check_name(item["name"]): item for item in checks}
    missing = [check for check in required_checks if canonical_check_name(check) not in by_canonical_name]
    if missing:
        raise SystemExit("GitHub Actions evidence is missing required checks: " + ", ".join(missing))
    ai_review_checks = [item for item in checks if is_ai_review_check(item["name"])]
    if require_ai_review and not ai_review_checks:
        raise SystemExit("GitHub Actions evidence must include Qodo PR-Agent, CodeRabbit, or another AI review check.")
    required_names = {canonical_check_name(check) for check in required_checks}
    must_pass = [item for name, item in by_canonical_name.items() if name in required_names]
    must_pass.extend(ai_review_checks)
    failing = sorted({item["name"] for item in must_pass if not passing_check(item)})
    if failing:
        raise SystemExit("GitHub Actions checks are not all passing: " + ", ".join(failing))
    return checks


def copy_report(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest.resolve():
        return
    shutil.copyfile(src, dest)


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    config = load_loop_config(args.config)
    if args.source_type not in config["source_types"]:
        raise SystemExit(f"Configured source_types do not allow {args.source_type!r} sources.")
    source = Path(args.source) if args.source else None
    if source and source.exists():
        shutil.copyfile(source, root / "source.md")
    elif not (root / "source.md").exists():
        raise SystemExit("A source spec is required. Pass --source <source.md> or create source.md first.")

    for name, text in TEMPLATES.items():
        path = root / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")

    state = {
        "phase": "planning",
        "created_at": now(),
        "updated_at": now(),
        "config": config,
        "source": str(source) if source else "",
        "source_type": args.source_type,
        "source_fingerprint": sha256_bytes((root / "source.md").read_bytes()),
        "reviews": {},
        "test_attempts": {},
        "quality_gate": {},
        "git": {},
        "github_actions": {},
        "blockers": [],
    }
    write_state(root, state)
    print(f"Initialized dev loop at {root}")
    return 0


def cmd_set_phase(args: argparse.Namespace) -> int:
    if args.phase not in PHASES:
        raise SystemExit(f"Unknown phase: {args.phase}")
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_config_allows_phase(state, args.phase)
    assert_transition(root, state, args.phase, workspace)
    if PHASE_INDEX[args.phase] < PHASE_INDEX[phase(state)]:
        clear_downstream_state(state, args.phase)
    state["phase"] = args.phase
    write_state(root, state)
    print(f"Phase set to {args.phase}")
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    print(f"PLAN_FINGERPRINT={plan_fingerprint(root)}")
    print(f"WORKSPACE_FINGERPRINT={workspace_fingerprint(workspace)}")
    return 0


def cmd_record_review(args: argparse.Namespace) -> int:
    role = args.role
    if role not in REVIEW_ROLES:
        raise SystemExit(f"Unknown review role: {role}")
    validate_agent_id(args.agent_id)
    src = Path(args.report)
    if not src.exists():
        raise SystemExit(f"Review report does not exist: {src}")
    decision = parse_decision(src)
    if decision not in {"pass", "needs-revision", "needs-human-review", "block"}:
        raise SystemExit(f"Review report has invalid or missing Decision: {src}")
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    validate_review_report(role, src, args.agent_id, root, workspace)
    if role == "plan-reviewer":
        assert_phase(state, {"planning", "plan_review"})
    elif role == "implementation-reviewer":
        assert_phase(state, {"implementation", "implementation_review"})
        if not all_planned_tests_passed(root, state, workspace):
            missing = ", ".join(missing_or_failing_units(root, state, workspace))
            raise SystemExit(f"Cannot record implementation review before all planned test gates pass: {missing}")
    elif role == "risk-reviewer":
        assert_phase(state, {"implementation_review", "risk_review"})
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot record risk review before implementation-reviewer passes.")
    dest = root / "reviews" / f"{role}.md"
    copy_report(src, dest)
    fingerprints = evidence_fingerprint(root, workspace)
    state["reviews"][role] = {
        "decision": decision,
        "path": str(dest),
        "agent_id": args.agent_id,
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"] if role != "plan-reviewer" else "",
        "report_fingerprint": sha256_bytes(dest.read_bytes()),
        "recorded_at": now(),
    }
    if decision == "block" or (role != "plan-reviewer" and decision != "pass"):
        add_blocker(state, f"{role} returned {decision}")
        write_state(root, state)
        print(f"{role}: {decision}")
        return 1
    write_state(root, state)
    print(f"{role}: {decision}")
    return 0


def record_test_meta(root: Path, workspace: Path, state: dict, unit: str, meta_path: Path) -> int:
    meta = load_test_meta(meta_path, unit, workspace)
    attempts = state.setdefault("test_attempts", {}).setdefault(unit, [])
    fingerprints = evidence_fingerprint(root, workspace)
    record = {
        "status": meta["status"],
        "command": meta["command"],
        "exit_code": meta.get("exit_code"),
        "log": meta["log_path"],
        "meta": str(meta_path),
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "recorded_at": now(),
    }
    attempts.append(record)
    failed_count = sum(1 for item in attempts if item.get("status") != "passed")
    configured_limit = loop_config(state)["test_failure_limit"]
    stop_after = 1 if configured_limit == 0 else configured_limit
    if failed_count >= stop_after and meta["status"] != "passed":
        add_blocker(state, f"{unit} test gate failed {failed_count} time(s); configured limit is {configured_limit}")
        write_state(root, state)
        print(f"{unit}: failed {failed_count} time(s)")
        return 1
    write_state(root, state)
    print(f"{unit}: {meta['status']} attempt {len(attempts)}")
    return 0


def cmd_run_test(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    script = Path(args.test_gate_script)
    if script.resolve() != DEFAULT_TEST_GATE_SCRIPT.resolve():
        assert_test_mode("Caller-supplied test gate scripts")
    if not script.exists():
        raise SystemExit(f"Test gate script does not exist: {script}")
    command = [
        sys.executable,
        str(script),
        "--unit",
        args.unit,
        "--command",
        args.command,
        "--cwd",
        str(workspace),
        "--timeout",
        str(args.timeout),
    ]
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    meta = parse_key_value_output(result.stdout, "AUTODEV_TEST_META")
    if not meta:
        raise SystemExit("Test gate did not report AUTODEV_TEST_META.")
    return record_test_meta(root, workspace, state, args.unit, Path(meta))


def record_quality_result(
    root: Path,
    workspace: Path,
    state: dict,
    summary: Path,
    results: Path,
    command: list[str],
    exit_code: int,
    stdout: str,
    required_gates: list[str],
    profile_name: str,
) -> int:
    if exit_code != 0:
        stdout_dest = root / "quality-gate-stdout.log"
        stdout_dest.write_text(stdout, encoding="utf-8", errors="replace")
        state["quality_gate"] = {
            "status": "failed",
            "stdout": str(stdout_dest),
            "command": command,
            "exit_code": exit_code,
            "recorded_at": now(),
        }
        add_blocker(state, f"quality gate process exited {exit_code}")
        write_state(root, state)
        print("Quality gate failed")
        return 1
    if not summary.exists():
        raise SystemExit(f"Quality summary does not exist: {summary}")
    decision = parse_quality_decision(summary)
    gate_results = validate_quality_results(results, required_gates, require_passed=True)
    required_gates_passed, deferred_human_review = quality_decision_allows_progress(decision, gate_results, required_gates)
    dest = root / "quality-gate-summary.md"
    copy_report(summary, dest)
    results_dest = root / "quality-gate-results.json"
    copy_report(results, results_dest)
    stdout_dest = root / "quality-gate-stdout.log"
    stdout_dest.write_text(stdout, encoding="utf-8", errors="replace")
    fingerprints = evidence_fingerprint(root, workspace)
    status = "passed" if required_gates_passed else "failed"
    state["quality_gate"] = {
        "summary": str(dest),
        "results": str(results_dest),
        "stdout": str(stdout_dest),
        "command": command,
        "exit_code": exit_code,
        "decision": decision,
        "status": status,
        "quality_profile": profile_name,
        "required_gates": required_gates,
        "deferred_human_review": deferred_human_review,
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "summary_fingerprint": sha256_bytes(dest.read_bytes()),
        "recorded_at": now(),
    }
    if status != "passed":
        add_blocker(state, f"quality gate decision was {decision}")
        write_state(root, state)
        print("Quality gate failed")
        return 1
    write_state(root, state)
    print("Quality gate passed")
    return 0


def cmd_run_quality(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"quality_gate"})
    assert_phase_prereqs(root, state, "quality_gate", workspace)
    script = DEFAULT_QUALITY_GATE_SCRIPT
    if not script.exists():
        raise SystemExit(f"Quality gate script does not exist: {script}")
    profile_name = loop_config(state)["quality_profile"]
    profile = quality_profile(state)
    profile_gates = list(profile["quality_gates"])
    extra_required_gates = split_csv(args.require)
    required_gates = merge_unique(profile_gates, extra_required_gates)
    out_dir = Path(args.out_dir) if args.out_dir else workspace / ".codex" / "quality-gate" / dt.datetime.now().strftime("%Y%m%d-%H%M%S-dev-loop")
    if out_dir.exists():
        raise SystemExit(f"Quality gate out-dir already exists; refusing to reuse stale artifacts: {out_dir}")
    alignment_report = Path(args.alignment_report)
    if not alignment_report.is_absolute():
        alignment_report = workspace / alignment_report
    command = [
        sys.executable,
        str(script),
        "--workspace",
        str(workspace),
        "--out-dir",
        str(out_dir),
        "--alignment-report",
        str(alignment_report),
        "--timeout",
        str(args.timeout),
    ]
    if profile.get("strict"):
        command.append("--strict")
    if required_gates:
        command.extend(["--require", ",".join(required_gates)])
    if args.pr_url:
        command.extend(["--pr-url", args.pr_url])
    for item in args.command:
        command.extend(["--command", item])
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    summary = out_dir / "summary.md"
    results = out_dir / "results.json"
    return record_quality_result(root, workspace, state, summary, results, command, result.returncode, result.stdout, required_gates, profile_name)


def cmd_record_branch(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"branch"})
    assert_phase_prereqs(root, state, "branch", workspace)
    if not is_git_repo(workspace):
        raise SystemExit("Cannot record a branch outside a git repository.")
    current_branch = current_git_branch(workspace)
    if current_branch != args.branch:
        raise SystemExit(f"Current git branch {current_branch!r} does not match requested branch {args.branch!r}.")
    if current_branch in PROTECTED_BRANCHES or current_branch.startswith("release/"):
        raise SystemExit(f"Refusing to use protected branch for dev loop: {current_branch}")
    state.setdefault("git", {})["branch"] = args.branch
    state["git"]["branch_recorded_at"] = now()
    write_state(root, state)
    print(f"Recorded branch: {args.branch}")
    return 0


def cmd_record_commit(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"quality_gate", "pr"})
    assert_phase_prereqs(root, state, "quality_gate", workspace)
    if not quality_is_current(state, root, workspace):
        raise SystemExit("Cannot record a commit before quality gate passes.")
    if not is_git_repo(workspace):
        raise SystemExit("Cannot record a commit outside a git repository.")
    current_branch = current_git_branch(workspace)
    recorded_branch = state.get("git", {}).get("branch")
    if recorded_branch and current_branch != recorded_branch:
        raise SystemExit(f"Current branch {current_branch!r} does not match recorded branch {recorded_branch!r}.")
    if current_branch in PROTECTED_BRANCHES or current_branch.startswith("release/"):
        raise SystemExit(f"Refusing to record a commit on protected branch: {current_branch}")
    current_head = current_git_head(workspace)
    if args.commit and args.commit != current_head:
        raise SystemExit(f"Current HEAD {current_head!r} does not match requested commit {args.commit!r}.")
    fingerprints = evidence_fingerprint(root, workspace)
    state["git"] = {
        **state.get("git", {}),
        "branch": recorded_branch or current_branch,
        "commit": current_head,
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "commit_recorded_at": now(),
    }
    write_state(root, state)
    print(f"Recorded commit: {current_head}")
    return 0


def cmd_record_pr(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"pr"})
    assert_phase_prereqs(root, state, "pr", workspace)
    if not is_git_repo(workspace):
        raise SystemExit("Cannot record a PR outside a git repository.")
    current_branch = current_git_branch(workspace)
    current_head = current_git_head(workspace)
    recorded_branch = state.get("git", {}).get("branch")
    if recorded_branch and recorded_branch != args.branch:
        raise SystemExit(f"PR branch {args.branch!r} does not match recorded branch {recorded_branch!r}")
    if current_branch != args.branch:
        raise SystemExit(f"Current branch {current_branch!r} does not match PR branch {args.branch!r}.")
    if current_head != args.commit:
        raise SystemExit(f"Current HEAD {current_head!r} does not match PR commit {args.commit!r}.")
    if "github.com/" not in args.pr_url or "/pull/" not in args.pr_url:
        raise SystemExit("PR URL must be a GitHub pull request URL.")
    expected_repo = git_origin_repository(workspace)
    if args.allow_local_simulation:
        assert_test_mode("PR local simulation")
        if not args.evidence:
            raise SystemExit("--evidence is required with --allow-local-simulation.")
        pr_data = validate_pr_evidence(load_json_file(Path(args.evidence)), args.branch, args.commit, args.pr_url, expected_repo)
    else:
        pr_data = validate_pr_evidence(
            run_gh_json(workspace, args.gh, ["pr", "view", args.pr_url, "--json", "url,headRefName,headRefOid,state,baseRepository"]),
            args.branch,
            args.commit,
            args.pr_url,
            expected_repo,
        )
    evidence_dest = root / "pr-evidence.json"
    evidence_dest.write_text(json.dumps(pr_data, indent=2), encoding="utf-8")
    fingerprints = evidence_fingerprint(root, workspace)
    state["git"] = {
        **state.get("git", {}),
        "branch": args.branch,
        "commit": args.commit,
        "pr_url": args.pr_url,
        "pr_evidence": str(evidence_dest),
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "recorded_at": now(),
    }
    write_state(root, state)
    print(f"Recorded PR: {args.pr_url}")
    return 0


def cmd_record_cloud(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"cloud_checks"})
    assert_phase_prereqs(root, state, "cloud_checks", workspace)
    profile = quality_profile(state)
    required_checks = [*profile["cloud_checks"], *args.extra_required_check]
    if args.allow_local_simulation:
        assert_test_mode("GitHub Actions local simulation")
        if not args.evidence:
            raise SystemExit("--evidence is required with --allow-local-simulation.")
        cloud_data = load_json_file(Path(args.evidence))
    else:
        pr_url = state.get("git", {}).get("pr_url")
        if not pr_url:
            raise SystemExit("Missing recorded PR URL for GitHub Actions checks.")
        cloud_data = run_gh_json(workspace, args.gh, ["pr", "checks", pr_url, "--json", "name,state,link"])
    checks = validate_cloud_evidence(cloud_data, required_checks, require_ai_review=bool(profile["require_ai_review"])) if args.status == "passed" else []
    evidence_dest = root / "github-actions-evidence.json"
    evidence_dest.write_text(json.dumps(cloud_data, indent=2), encoding="utf-8")
    fingerprints = evidence_fingerprint(root, workspace)
    state["github_actions"] = {
        "status": args.status,
        "evidence": str(evidence_dest),
        "checks": checks,
        "required_checks": required_checks,
        "quality_profile": loop_config(state)["quality_profile"],
        "require_ai_review": bool(profile["require_ai_review"]),
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "recorded_at": now(),
    }
    if args.status != "passed":
        add_blocker(state, "GitHub Actions cloud checks failed or are blocked")
        write_state(root, state)
        print("GitHub Actions cloud checks blocked")
        return 1
    write_state(root, state)
    print("GitHub Actions cloud checks passed")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    automation_level = loop_config(state)["automation_level"]
    findings: list[str] = []
    try:
        assert_core_artifacts(root)
    except SystemExit as exc:
        findings.append(str(exc))
    if args.require_reviews:
        roles = ["plan-reviewer"] if automation_level == "planning_only" else sorted(REVIEW_ROLES)
        for role in roles:
            if not review_is_current(state, role, root, workspace):
                findings.append(f"Missing current passing review: {role}")
    if args.require_final:
        final_records = ["final-report.md"]
        if automation_level != "planning_only":
            final_records.extend(["quality-gate-summary.md", "quality-gate-results.json"])
        if automation_level == "pr_without_merge":
            final_records.extend(["pr-body.md", "github-actions.md"])
        for name in final_records:
            if not (root / name).exists():
                findings.append(f"Missing final record: {name}")
        git = state.get("git", {})
        if automation_level != "planning_only" and not git.get("commit"):
            findings.append("Missing commit hash")
        if automation_level == "pr_without_merge" and not git.get("pr_url"):
            findings.append("Missing PR URL")
        if automation_level != "planning_only" and not quality_is_current(state, root, workspace):
            findings.append("Quality gate is not recorded as current and passed")
        if automation_level == "commit_only" and not git_commit_is_current(state, root, workspace):
            findings.append("Commit record is not current")
        if automation_level == "pr_without_merge" and not git_pr_is_current(state, root, workspace):
            findings.append("PR record is not current")
        if automation_level == "pr_without_merge" and not cloud_is_current(state, root, workspace):
            findings.append("GitHub Actions cloud checks are not recorded as current and passed")
    if state.get("blockers"):
        findings.extend(f"Blocker: {item}" for item in state["blockers"])
    if findings:
        print("Dev loop harness validation failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Dev loop harness state is valid.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex dev loop state helper.")
    parser.add_argument("--root", default=".codex/dev-loop")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--config", default=os.environ.get("CODEX_DEV_LOOP_CONFIG", ""), help="Path to codex-dev-loop config JSON.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("--source", default="")
    init.add_argument("--source-type", choices=sorted(SOURCE_TYPES), default="markdown")
    init.set_defaults(func=cmd_init)

    phase = sub.add_parser("set-phase")
    phase.add_argument("phase")
    phase.set_defaults(func=cmd_set_phase)

    fingerprint = sub.add_parser("fingerprint")
    fingerprint.set_defaults(func=cmd_fingerprint)

    branch = sub.add_parser("record-branch")
    branch.add_argument("--branch", required=True)
    branch.set_defaults(func=cmd_record_branch)

    commit = sub.add_parser("record-commit")
    commit.add_argument("--commit", default="")
    commit.set_defaults(func=cmd_record_commit)

    review = sub.add_parser("record-review")
    review.add_argument("--role", required=True)
    review.add_argument("--report", required=True)
    review.add_argument("--agent-id", required=True)
    review.set_defaults(func=cmd_record_review)

    test = sub.add_parser("run-test")
    test.add_argument("--unit", required=True)
    test.add_argument("--command", required=True)
    test.add_argument("--timeout", type=int, default=600)
    test.add_argument("--test-gate-script", default=str(DEFAULT_TEST_GATE_SCRIPT))
    test.set_defaults(func=cmd_run_test)

    quality = sub.add_parser("run-quality")
    quality.add_argument("--out-dir", default="")
    quality.add_argument("--alignment-report", default=".codex/quality-gate/subagent-alignment.md")
    quality.add_argument("--timeout", type=int, default=900)
    quality.add_argument("--require", default="", help="Additional required gates; configured profile gates are always required.")
    quality.add_argument("--pr-url", default="")
    quality.add_argument("--command", action="append", default=[], metavar="GATE=COMMAND")
    quality.set_defaults(func=cmd_run_quality)

    pr = sub.add_parser("record-pr")
    pr.add_argument("--branch", required=True)
    pr.add_argument("--commit", required=True)
    pr.add_argument("--pr-url", required=True)
    pr.add_argument("--gh", default="gh")
    pr.add_argument("--evidence", default="")
    pr.add_argument("--allow-local-simulation", action="store_true")
    pr.set_defaults(func=cmd_record_pr)

    cloud = sub.add_parser("record-cloud")
    cloud.add_argument("--status", required=True, choices=["passed", "failed", "blocked"])
    cloud.add_argument("--gh", default="gh")
    cloud.add_argument("--evidence", default="")
    cloud.add_argument("--extra-required-check", action="append", default=[])
    cloud.add_argument("--allow-local-simulation", action="store_true")
    cloud.set_defaults(func=cmd_record_cloud)

    validate = sub.add_parser("validate")
    validate.add_argument("--require-reviews", action="store_true")
    validate.add_argument("--require-final", action="store_true")
    validate.set_defaults(func=cmd_validate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
