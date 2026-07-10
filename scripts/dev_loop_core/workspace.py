"""Workspace, git, fingerprint, unit, scope, and budget primitives."""

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
    CORE_ARTIFACTS,
    DOCS_IMPACT_REVIEWER_ROLE,
    MERGE_INTEGRATOR_ROLE,
    PHASE_INDEX,
    REQUIREMENTS_REVIEWER_ROLE,
    SCOPE_ALWAYS_IGNORED_PREFIXES,
    SCOPE_FORMATTING_CHURN_THRESHOLD,
    SCOPE_FORMATTING_FILE_THRESHOLD,
    SENSITIVE_DIR_TOKENS,
    SENSITIVE_FILE_NAMES,
    SENSITIVE_SUFFIXES,
    TDD_MODES,
    TEST_MODE_ENV,
    loop_config,
    loop_scale,
    now,
)
from .specs import (
    parse_spec_delta,
)

def normalize_repo_path(path: str) -> str:
    normalized = path.strip().strip('"').replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def git_name_only(workspace: Path, args: list[str]) -> list[str]:
    completed = run_git(workspace, args)
    if completed.returncode != 0:
        return []
    return [normalize_repo_path(line) for line in completed.stdout.splitlines() if normalize_repo_path(line)]


def status_workspace_paths(workspace: Path) -> list[str]:
    completed = run_git(workspace, ["status", "--porcelain", "-uall"], check=True)
    paths: list[str] = []
    for raw_line in completed.stdout.splitlines():
        if len(raw_line) < 4:
            continue
        entry = raw_line[3:].strip().strip('"')
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1].strip().strip('"')
        normalized = normalize_repo_path(entry)
        if normalized:
            paths.append(normalized)
    return paths


def changed_workspace_paths(workspace: Path, base_ref: str = "") -> list[str]:
    """Staged, unstaged, untracked, and optionally branch-diff paths."""
    paths = status_workspace_paths(workspace)
    if base_ref:
        diff_paths = git_name_only(workspace, ["diff", "--name-only", f"{base_ref}...HEAD"])
        if not diff_paths:
            diff_paths = git_name_only(workspace, ["diff", "--name-only", f"{base_ref}..HEAD"])
        paths.extend(diff_paths)
    seen: set[str] = set()
    unique: list[str] = []
    for item in paths:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def is_sensitive_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    parts = [part.lower() for part in normalized.split("/") if part]
    if not parts:
        return False
    name = parts[-1]
    return (
        name in SENSITIVE_FILE_NAMES
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.startswith("dockerfile")
        or name.startswith(".env")
        or "secret" in name
        or "credential" in name
        or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
        or any(part in SENSITIVE_DIR_TOKENS for part in parts[:-1])
    )


def sensitive_changed_paths(workspace: Path) -> list[str]:
    return [path for path in changed_workspace_paths(workspace) if is_sensitive_path(path)]


def scope_ignored_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    return any(normalized.startswith(prefix) for prefix in SCOPE_ALWAYS_IGNORED_PREFIXES)


def extract_scope_paths_from_text(text: str) -> list[str]:
    paths: list[str] = []
    in_file_scope = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("## "):
            in_file_scope = lower.startswith("## file and module scope")
            continue
        relevant = in_file_scope or lower.startswith("- scope:") or lower.startswith("scope:")
        if not relevant:
            continue
        if ":" in line and lower.startswith(("- scope:", "scope:")):
            line = line.split(":", 1)[1]
        line = line.replace("`", " ").replace("[", " ").replace("]", " ")
        for token in re.split(r"[\s,;]+", line):
            cleaned = token.strip().strip("'\"()[]{}<>").rstrip(".:")
            cleaned = normalize_repo_path(cleaned)
            if not cleaned or cleaned.lower() in {"none", "n/a", "na", "tbd", "todo"}:
                continue
            if "://" in cleaned or cleaned.startswith("#"):
                continue
            if any(char in cleaned for char in ("/", "*")) or "." in Path(cleaned).name:
                paths.append(cleaned)
    seen: set[str] = set()
    unique: list[str] = []
    for item in paths:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def declared_scope_paths(root: Path, state: dict | None = None, plan_path: Path | None = None, design_path: Path | None = None) -> list[str]:
    plan_path = plan_path or (root / "development-plan.md")
    design_path = design_path or (root / "technical-design.md")
    paths: list[str] = []
    for item in (design_path, plan_path):
        if item.exists():
            paths.extend(extract_scope_paths_from_text(item.read_text(encoding="utf-8", errors="replace")))
    if state is not None:
        try:
            delta = parse_spec_delta((root / "spec-delta.md").read_text(encoding="utf-8", errors="replace"))
            spec_dir = loop_config(state).get("spec_dir", "specs")
            for capability in delta.get("capabilities", {}):
                paths.append(normalize_repo_path(f"{spec_dir}/{capability}.md"))
        except Exception:
            pass
    seen: set[str] = set()
    unique: list[str] = []
    for item in paths:
        normalized = normalize_repo_path(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def path_in_declared_scope(path: str, declared: list[str]) -> bool:
    normalized = normalize_repo_path(path)
    for scope in declared:
        item = normalize_repo_path(scope)
        if not item:
            continue
        if fnmatch.fnmatch(normalized, item):
            return True
        if item.endswith("/") and normalized.startswith(item):
            return True
        if normalized == item or normalized.startswith(item.rstrip("/") + "/"):
            return True
    return False


def diff_line_churn(workspace: Path, base_ref: str = "") -> int:
    commands: list[list[str]] = []
    if base_ref:
        commands.append(["diff", "--numstat", f"{base_ref}...HEAD"])
    commands.append(["diff", "--numstat", "HEAD"])
    total = 0
    for command in commands:
        completed = run_git(workspace, command)
        if completed.returncode != 0 or not completed.stdout.strip():
            continue
        for raw_line in completed.stdout.splitlines():
            parts = raw_line.split("	")
            if len(parts) < 3:
                continue
            for value in parts[:2]:
                if value.isdigit():
                    total += int(value)
    untracked = run_git(workspace, ["ls-files", "-z", "--others", "--exclude-standard"])
    if untracked.returncode == 0:
        for item in (value for value in untracked.stdout.split("\0") if value):
            normalized = normalize_repo_path(item)
            if is_excluded_workspace_path(normalized):
                continue
            path = workspace / normalized
            if not path.is_file():
                continue
            data = path.read_bytes()
            if b"\0" in data:
                total += max(1, (len(data) + 79) // 80)
            elif data:
                total += data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
    return total


def scope_check_result(
    root: Path,
    workspace: Path,
    state: dict | None = None,
    plan_path: Path | None = None,
    design_path: Path | None = None,
    base_ref: str = "",
) -> dict:
    changed = [path for path in changed_workspace_paths(workspace, base_ref=base_ref) if not scope_ignored_path(path)]
    declared = declared_scope_paths(root, state=state, plan_path=plan_path, design_path=design_path)
    sensitive_changed = [path for path in changed if is_sensitive_path(path)]
    out_of_scope = [path for path in changed if not path_in_declared_scope(path, declared)]
    findings: list[str] = []
    if changed and not declared:
        findings.append("No declared file scope found in technical-design.md or development-plan.md.")
    if out_of_scope:
        findings.append("Changed paths outside declared scope: " + ", ".join(sorted(out_of_scope)))
    scale = loop_scale(state) if state else ""
    if sensitive_changed and (not scale or scale == "small"):
        findings.append(
            "Sensitive paths changed; escalate scale to standard/large and run the real risk review: "
            + ", ".join(sorted(sensitive_changed))
        )
    churn = diff_line_churn(workspace, base_ref=base_ref)
    if len(changed) >= SCOPE_FORMATTING_FILE_THRESHOLD or churn >= SCOPE_FORMATTING_CHURN_THRESHOLD:
        findings.append(
            f"Large formatting/noise risk: {len(changed)} changed file(s), {churn} changed line(s). Split formatting from behavior or declare the wider scope."
        )
    return {
        "status": "passed" if not findings else "failed",
        "changed_paths": changed,
        "declared_scope": declared,
        "out_of_scope": out_of_scope,
        "sensitive_paths": sensitive_changed,
        "line_churn": churn,
        "findings": findings,
    }


def print_scope_check(result: dict) -> None:
    print(f"SCOPE_CHECK_STATUS={result['status']}")
    print("SCOPE_CHECK_CHANGED=" + (", ".join(result["changed_paths"]) or "none"))
    print("SCOPE_CHECK_DECLARED=" + (", ".join(result["declared_scope"]) or "none"))
    if result["findings"]:
        print("Scope check findings:")
        for finding in result["findings"]:
            print(f"- {finding}")


def scope_check_base_ref(state: dict, run_cwd: Path, workspace: Path) -> str:
    git = state.get("git", {})
    if run_cwd.resolve() != workspace.resolve():
        return git.get("branch", "")
    return git.get("base_commit", "")


def budget_check_result(root: Path, workspace: Path, state: dict, run_cwd: Path | None = None, include_diff: bool = True, include_units: bool = True) -> dict:
    run_cwd = run_cwd or workspace
    config = loop_config(state)
    units = planned_units(root) if include_units else []
    findings: list[str] = []
    if include_units and len(units) > config["max_units"]:
        findings.append(f"max_units exceeded: {len(units)} planned unit(s) > {config['max_units']}.")
    changed: list[str] = []
    churn = 0
    if include_diff and is_git_repo(run_cwd):
        base_ref = scope_check_base_ref(state, run_cwd, workspace)
        changed = [path for path in changed_workspace_paths(run_cwd, base_ref=base_ref) if not scope_ignored_path(path)]
        churn = diff_line_churn(run_cwd, base_ref=base_ref)
        if len(changed) > config["max_files_changed"]:
            findings.append(f"max_files_changed exceeded: {len(changed)} changed file(s) > {config['max_files_changed']}.")
        if churn > config["max_diff_lines"]:
            findings.append(f"max_diff_lines exceeded: {churn} changed line(s) > {config['max_diff_lines']}.")
    return {
        "status": "passed" if not findings else "failed",
        "planned_units": len(units),
        "changed_paths": changed,
        "line_churn": churn,
        "findings": findings,
    }


def print_budget_check(result: dict) -> None:
    print(f"BUDGET_CHECK_STATUS={result['status']}")
    print(f"BUDGET_CHECK_UNITS={result['planned_units']}")
    print("BUDGET_CHECK_CHANGED=" + (", ".join(result["changed_paths"]) or "none"))
    print(f"BUDGET_CHECK_DIFF_LINES={result['line_churn']}")
    if result["findings"]:
        print("Budget/time-box findings:")
        for finding in result["findings"]:
            print(f"- {finding}")


def run_budget_check_hook(
    root: Path,
    workspace: Path,
    state: dict,
    context: str,
    run_cwd: Path | None = None,
    include_diff: bool = True,
    include_units: bool = True,
) -> bool:
    result = budget_check_result(root, workspace, state, run_cwd=run_cwd, include_diff=include_diff, include_units=include_units)
    state["budget_check"] = {**result, "context": context, "recorded_at": now()}
    if result["status"] == "passed":
        return True
    add_blocker(state, f"budget/time-box reached at {context}: " + "; ".join(result["findings"]))
    print_budget_check(result)
    return False


def run_scope_check_hook(root: Path, workspace: Path, state: dict, context: str, run_cwd: Path | None = None) -> bool:
    run_cwd = run_cwd or workspace
    result = scope_check_result(root, run_cwd, state=state, base_ref=scope_check_base_ref(state, run_cwd, workspace))
    state["scope_check"] = {**result, "context": context, "recorded_at": now()}
    if result["status"] == "passed":
        return True
    add_blocker(state, f"scope-check failed at {context}: " + "; ".join(result["findings"]))
    print_scope_check(result)
    return False


def assert_small_scale_skip_allowed(state: dict, workspace: Path) -> None:
    sensitive = sensitive_changed_paths(workspace)
    if sensitive:
        raise SystemExit(
            "Small scale cannot skip risk review: sensitive paths changed ("
            + ", ".join(sorted(sensitive))
            + "). Run the risk review phase (backtrack with set-phase) or keep scale at standard or large."
        )


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
    try:
        state, _report = load_evidence_document(path, "loop-state")
    except EvidenceContractError as exc:
        raise SystemExit(f"Cannot trust loop state {path}: {exc}") from exc
    return state


def write_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    path = root / "loop-state.json"
    try:
        write_evidence_document(path, state, "loop-state")
    except EvidenceContractError as exc:
        raise SystemExit(f"Cannot write loop state {path}: {exc}") from exc


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


def source_fingerprint(root: Path) -> str:
    """Bind requirements review to every artifact the reviewer receives."""
    return hash_files(root, ["source.md", "clarification-log.md"])


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
    return {"source": source_fingerprint(root), "plan": plan_fingerprint(root), "workspace": workspace_fingerprint(workspace)}


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


def unit_tdd_modes(root: Path) -> dict[str, str]:
    """Per-unit TDD mode from development-plan.md.

    `- TDD: red` (default) requires recorded failing red evidence before a
    green run counts. `- TDD: regression-only` waives the red stage for units
    that are covered by existing tests (refactors); the waiver sits in the
    plan on purpose so plan review has to approve it.
    """
    plan = root / "development-plan.md"
    modes: dict[str, str] = {}
    if not plan.exists():
        return modes
    current = ""
    for raw_line in plan.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.lower().startswith("## unit "):
            current = line.split(None, 2)[-1].strip()
            continue
        if current and line.lower().startswith("- tdd:"):
            modes[current] = line.split(":", 1)[1].strip().lower()
    return modes


def unit_tdd_mode(root: Path, unit: str) -> str:
    mode = unit_tdd_modes(root).get(unit, "red")
    if not mode:
        return "red"
    if mode not in TDD_MODES:
        raise SystemExit(f"Unit {unit} has invalid '- TDD:' value {mode!r}; use one of: {', '.join(sorted(TDD_MODES))}.")
    return mode


def attempt_stage(record: dict) -> str:
    return record.get("stage") or "green"


def red_validation_allows_evidence(record: dict) -> bool:
    validation = record.get("red_validation")
    if not isinstance(validation, dict):
        # Compatibility with evidence recorded before red-test-validator existed.
        return True
    return validation.get("status") == "pass"


def unit_has_red_evidence(root: Path, state: dict, unit: str) -> bool:
    """A red run proves the test can fail for the intended reason; only failed,
    validator-passed evidence counts and it must match the reviewed plan."""
    for record in state.get("test_attempts", {}).get(unit, []):
        if attempt_stage(record) != "red":
            continue
        if record.get("status") != "failed":
            continue
        if not red_validation_allows_evidence(record):
            continue
        if record.get("plan_fingerprint") == plan_fingerprint(root):
            return True
    return False


def unit_red_gate_satisfied(root: Path, state: dict, unit: str) -> bool:
    if unit_tdd_mode(root, unit) == "regression-only":
        return True
    return unit_has_red_evidence(root, state, unit)


def latest_test_status(state: dict, unit: str) -> str:
    attempts = state.get("test_attempts", {}).get(unit, [])
    if not attempts:
        return ""
    return attempts[-1].get("status", "")


def unit_green_is_current(record: dict, root: Path, workspace: Path) -> bool:
    if record.get("status") != "passed" or attempt_stage(record) != "green":
        return False
    return current_record(record, root, workspace, include_workspace=True)


def has_worktree_evidence(state: dict) -> bool:
    return any(record.get("worktree") for attempts in state.get("test_attempts", {}).values() for record in attempts)


def required_review_roles(state: dict, automation_level: str) -> list[str]:
    if automation_level == "planning_only":
        return [REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer"]
    roles = [REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer", "implementation-reviewer", DOCS_IMPACT_REVIEWER_ROLE]
    if loop_scale(state) != "small":
        roles.append("risk-reviewer")
    if has_worktree_evidence(state):
        roles.insert(2, MERGE_INTEGRATOR_ROLE)
    return roles


def valid_review_decisions(role: str) -> set[str]:
    if role == DOCS_IMPACT_REVIEWER_ROLE:
        return {"no-docs-needed", "docs-needed", "block"}
    return {"pass", "needs-revision", "needs-human-review", "block"}


def review_decision_allows_progress(role: str, decision: str) -> bool:
    if role == DOCS_IMPACT_REVIEWER_ROLE:
        return decision == "no-docs-needed"
    return decision == "pass"


def all_planned_tests_passed(root: Path, state: dict, workspace: Path) -> bool:
    units = planned_units(root)
    if not units:
        return False
    for unit in units:
        attempts = state.get("test_attempts", {}).get(unit, [])
        if not attempts:
            return False
        if not unit_green_is_current(attempts[-1], root, workspace):
            return False
        if not unit_red_gate_satisfied(root, state, unit):
            return False
    return True


def missing_or_failing_units(root: Path, state: dict, workspace: Path) -> list[str]:
    missing: list[str] = []
    for unit in planned_units(root):
        attempts = state.get("test_attempts", {}).get(unit, [])
        if not attempts:
            missing.append(unit)
            continue
        if not unit_green_is_current(attempts[-1], root, workspace):
            missing.append(unit)
            continue
        if not unit_red_gate_satisfied(root, state, unit):
            missing.append(f"{unit} (missing red-stage TDD evidence)")
    return missing


def add_blocker(state: dict, message: str) -> None:
    blockers = state.setdefault("blockers", [])
    if message not in blockers:
        blockers.append(message)


def review_iteration_count(state: dict, role: str) -> int:
    return int(state.get("review_iterations", {}).get(role, 0) or 0)


def increment_review_iteration(state: dict, role: str) -> None:
    iterations = state.setdefault("review_iterations", {})
    iterations[role] = review_iteration_count(state, role) + 1


def run_review_budget_hook(root: Path, workspace: Path, state: dict, role: str) -> bool:
    limit = loop_config(state)["max_review_iterations"]
    count = review_iteration_count(state, role)
    if count < limit:
        return True
    result = {
        "status": "failed",
        "planned_units": len(planned_units(root)),
        "changed_paths": [],
        "line_churn": 0,
        "findings": [f"max_review_iterations exceeded for {role}: {count} recorded iteration(s) >= {limit}."],
    }
    state["budget_check"] = {**result, "context": f"before {role} review", "recorded_at": now()}
    add_blocker(state, f"budget/time-box reached before {role} review: " + "; ".join(result["findings"]))
    print_budget_check(result)
    return False


def quality_failure_rounds(state: dict) -> int:
    return int(state.get("budget_usage", {}).get("quality_fix_rounds", 0) or 0)


def increment_quality_failure_round(state: dict) -> None:
    usage = state.setdefault("budget_usage", {})
    usage["quality_fix_rounds"] = quality_failure_rounds(state) + 1


def run_quality_budget_hook(root: Path, workspace: Path, state: dict) -> bool:
    limit = loop_config(state)["max_quality_fix_rounds"]
    count = quality_failure_rounds(state)
    if count == 0 or count < limit:
        return True
    result = {
        "status": "failed",
        "planned_units": len(planned_units(root)),
        "changed_paths": [],
        "line_churn": 0,
        "findings": [f"max_quality_fix_rounds exceeded: {count} failed quality round(s) >= {limit}."],
    }
    state["budget_check"] = {**result, "context": "before quality gate", "recorded_at": now()}
    add_blocker(state, "budget/time-box reached before quality gate: " + "; ".join(result["findings"]))
    print_budget_check(result)
    return False


def assert_no_blockers(state: dict) -> None:
    blockers = state.get("blockers") or []
    if blockers:
        raise SystemExit("Loop is blocked: " + "; ".join(blockers))
