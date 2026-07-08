#!/usr/bin/env python3
"""State helper for the Codex dev loop.

This does not replace Codex as the harness. It provides a small enforceable
state ledger that Codex can call while running the loop.
"""

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

REQUIREMENTS_REVIEWER_ROLE = "requirements-reviewer"
MERGE_INTEGRATOR_ROLE = "merge-integrator"
DOCS_IMPACT_REVIEWER_ROLE = "docs-impact-reviewer"
REVIEW_ROLES = {REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer", MERGE_INTEGRATOR_ROLE, "implementation-reviewer", DOCS_IMPACT_REVIEWER_ROLE, "risk-reviewer"}
PROTECTED_BRANCHES = {"main", "master", "develop"}
CORE_ARTIFACTS = ["source.md", "technical-design.md", "test-plan.md", "risk-analysis.md", "development-plan.md", "spec-delta.md", "decision-log.md"]
FINAL_ARTIFACTS = ["final-report.md", "pr-body.md", "quality-gate-summary.md"]
SCALES = ["small", "standard", "large"]
SCALE_INDEX = {scale: index for index, scale in enumerate(SCALES)}
TDD_MODES = {"red", "regression-only"}
TEST_STAGES = {"red", "green"}
# Paths whose changes must never ship through the small-scale shortcut that
# skips risk review. Matching is fail-closed: when any changed path matches,
# the harness refuses the skip and requires a real risk review.
SENSITIVE_FILE_NAMES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
    "pyproject.toml", "poetry.lock", "uv.lock", "pipfile", "pipfile.lock", "setup.py", "setup.cfg",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "gemfile", "gemfile.lock",
    "composer.json", "composer.lock", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".gitlab-ci.yml", "jenkinsfile",
}
SENSITIVE_DIR_TOKENS = {".github", "migrations", "migration", "migrate", "auth", "security", "secrets", "crypto"}
SENSITIVE_SUFFIXES = {".sql", ".tf", ".pem", ".key"}
AI_REVIEW_CHECK_ALIASES = ["qodo", "coderabbit", "pr-agent", "ai-review"]
# Real-world GitHub check names rarely equal the canonical gate name (for
# example "SonarCloud Code Analysis" for the sonar gate). Each required check
# also matches when one of these single-token vendor aliases appears as a
# hyphen-delimited token in the canonical check name. Loop-owned checks such
# as ai-quality-gate and subagent-alignment intentionally have no aliases and
# still require an exact canonical match.
RED_FAILURE_INFRA_PATTERNS = [
    ("import/dependency error", ["modulenotfounderror", "importerror", "cannot find module", "err_module_not_found", "cannot find package"]),
    ("syntax error", ["syntaxerror", "indentationerror", "taberror"]),
    ("test collection error", ["error collecting", "errors during collection", "failed to import test module", "import file mismatch"]),
    ("missing fixture", ["fixture", "not found"]),
    ("environment or path error", ["could not start test command", "command not found", "is not recognized as an internal or external command", "no such file or directory", "filenotfounderror", "enoent", "can't open file"]),
    ("tooling/config error", ["failed to load config", "npm err!", "error: cannot find", "pytest: error"]),
]
RED_FAILURE_SNAPSHOT_PATTERNS = ["snapshot", "snapshots:", "snapshot summary", "received value does not match stored snapshot"]
EXPECTED_FAILURE_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "when", "then", "into", "from", "missing", "fails", "fail", "error",
}
SCOPE_FORMATTING_FILE_THRESHOLD = 25
SCOPE_FORMATTING_CHURN_THRESHOLD = 3000
SCOPE_ALWAYS_IGNORED_PREFIXES = (".codex/",)


SCANNER_CHECK_ALIASES = {
    "sonar": ["sonar", "sonarcloud", "sonarqube"],
    "qodana": ["qodana"],
    "codeql": ["codeql"],
    "semgrep": ["semgrep"],
}
HOME_ENV = "CODEX_DEV_LOOP_HOME"


def codex_home() -> Path:
    """Agent home for config and companion skills.

    Defaults to ~/.codex; CODEX_DEV_LOOP_HOME relocates it so other agents
    (for example Claude Code with ~/.claude) can host the same loop.
    """
    override = os.environ.get(HOME_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex"


def default_config_path() -> Path:
    return codex_home() / "config" / "codex-dev-loop.json"


def default_test_gate_script() -> Path:
    return codex_home() / "skills" / "automated-dev-executor" / "scripts" / "test_gate.py"


def default_quality_gate_script() -> Path:
    return codex_home() / "skills" / "ai-code-quality-gate" / "scripts" / "quality_gate.py"


BUNDLED_TEST_GATE_SCRIPT = Path(__file__).resolve().parent / "test_gate.py"
BUNDLED_QUALITY_GATE_SCRIPT = Path(__file__).resolve().parent / "quality_gate_fallback.py"
TEST_MODE_ENV = "CODEX_DEV_LOOP_TEST_MODE"
# Harness core version for the composable sub-skills (dev-tdd, dev-review, ...).
# Sub-skills declare a minimum and can verify it with `version --require`.
CORE_VERSION = "0.5.1"
# Standalone evidence lives inside the workspace so it stays visible to git and
# reviewers, exactly like loop evidence. The canonical loop dir is what the
# single-source-of-truth guard watches for an in-flight loop.
DEFAULT_EVIDENCE_DIRNAME = ".codex/evidence"
CANONICAL_LOOP_DIR = ".codex/dev-loop"
CONFIG_SCHEMA_VERSION = 3
DEFAULT_CONFIG = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "automation_level": "pr_without_merge",
    "source_types": ["markdown", "notion"],
    "quality_profile": "standard",
    "test_failure_limit": 3,
    "max_units": 8,
    "max_files_changed": 20,
    "max_test_retries_per_unit": 3,
    "max_review_iterations": 3,
    "max_quality_fix_rounds": 2,
    "max_diff_lines": 1200,
    "risk_mode": "stop_and_ask",
    "default_scale": "standard",
    "spec_dir": "specs",
    "test_gate_script": "",
    "quality_gate_script": "",
    "evidence_dir": "",
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
    REQUIREMENTS_REVIEWER_ROLE: [
        "Requirement Quality Matrix:",
        "Observability:",
        "Failure Conditions:",
        "Boundaries:",
        "Non-Goals:",
        "Test Mapping:",
        "Blocking Questions:",
    ],
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
    MERGE_INTEGRATOR_ROLE: [
        "Merged Units:",
        "Diff Interaction:",
        "Duplicate Logic:",
        "Shared Interface Assumptions:",
        "Test Interaction:",
        "Hidden Conflict Risks:",
        "Integration Test Recommendation:",
        "Required Actions:",
    ],
    DOCS_IMPACT_REVIEWER_ROLE: [
        "Docs Impact",
        "Required Doc Changes",
        "Reason",
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
    ("planning", "intake"),
    ("plan_review", "intake"),
    ("plan_review", "planning"),
    ("implementation_review", "implementation"),
    ("risk_review", "implementation"),
    ("quality_gate", "implementation"),
    ("pr", "implementation"),
    ("cloud_checks", "implementation"),
    ("complete", "implementation"),
}

DRAFT_SOURCE_TEMPLATE = "# Source\n\n## Goal\n\n## Acceptance Criteria\n\n## Context\n\n## Constraints\n\n## Open Questions\n"

TEMPLATES = {
    "technical-design.md": "# Technical Design\n\n## Goal\n\n## Acceptance Criteria\n\n## Proposed Approach\n\n## File And Module Scope\n\n## Data Model Or API Changes\n\n## Dependencies\n\n## Non-Goals\n\n## Open Questions\n",
    "test-plan.md": "# Test Plan\n\n## Unit Tests\n\n## Integration Tests\n\n## E2E Or Browser Tests\n\n## Static Gates\n\n## Manual Checks\n\n## Coverage Gaps\n",
    "risk-analysis.md": "# Risk Analysis\n\n## Correctness Risks\n\n## Security Risks\n\n## Data Or Migration Risks\n\n## Architecture Risks\n\n## Compatibility Risks\n\n## External Service Or Credential Risks\n\n## Mitigations\n",
    "development-plan.md": "# Development Plan\n\n## Unit dev-001\n\n- Objective:\n- Scope:\n- Acceptance:\n- Test gate:\n- TDD: red\n- Dependencies:\n- Status: pending\n- Evidence:\n",
    "spec-delta.md": "# Spec Delta\n\nDescribe requirement-level changes per capability, or justify no impact.\nEach `## Capability: <kebab-name>` maps to `<spec-dir>/<kebab-name>.md` in the repository.\nList each requirement as `#### Requirement: <title>` under ADDED/MODIFIED/REMOVED.\n\n## Capability: <name>\n\n### ADDED Requirements\n\n### MODIFIED Requirements\n\n### REMOVED Requirements\n\n## No Spec Impact\n",
    "clarification-log.md": "# Clarification Log\n\n## Open Questions\n\n## Answered\n\n| Question | Answer | Source | Date |\n| --- | --- | --- | --- |\n\n## Assumptions Approved By User\n",
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


def normalize_int_config(config: dict, key: str, minimum: int) -> int:
    try:
        value = int(config.get(key))
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{key} in codex-dev-loop config must be an integer.") from exc
    if value < minimum:
        raise SystemExit(f"{key} in codex-dev-loop config must be >= {minimum}.")
    config[key] = value
    return value


def normalize_config(raw: object) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("codex-dev-loop config must be a JSON object.")
    raw_config = dict(raw)
    config = default_config()
    config.update(raw_config)
    if "max_test_retries_per_unit" not in raw_config and "test_failure_limit" in raw_config:
        config["max_test_retries_per_unit"] = raw_config["test_failure_limit"]

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
    normalize_int_config(config, "max_units", 1)
    normalize_int_config(config, "max_files_changed", 1)
    normalize_int_config(config, "max_test_retries_per_unit", 0)
    normalize_int_config(config, "max_review_iterations", 1)
    normalize_int_config(config, "max_quality_fix_rounds", 0)
    normalize_int_config(config, "max_diff_lines", 1)
    config["test_failure_limit"] = config["max_test_retries_per_unit"]
    if config.get("default_scale") not in SCALE_INDEX:
        raise SystemExit(f"Invalid default_scale in codex-dev-loop config: {config.get('default_scale')!r}")
    spec_dir = str(config.get("spec_dir") or "").strip().replace("\\", "/")
    if not spec_dir or spec_dir.startswith("/") or spec_dir.startswith("~") or ":" in spec_dir or ".." in spec_dir.split("/"):
        raise SystemExit(f"spec_dir in codex-dev-loop config must be a relative path inside the repository: {config.get('spec_dir')!r}")
    config["spec_dir"] = spec_dir
    for key in ("test_gate_script", "quality_gate_script"):
        if not isinstance(config.get(key), str):
            raise SystemExit(f"{key} in codex-dev-loop config must be a string path or empty.")
    evidence_dir = str(config.get("evidence_dir") or "").strip().replace("\\", "/")
    if evidence_dir and (evidence_dir.startswith("/") or evidence_dir.startswith("~") or ":" in evidence_dir or ".." in evidence_dir.split("/")):
        raise SystemExit(f"evidence_dir in codex-dev-loop config must be empty or a relative path inside the repository: {config.get('evidence_dir')!r}")
    config["evidence_dir"] = evidence_dir
    # Schema v1 configs are accepted as-is: every v2 key falls back to its
    # default above, so first-run users never have to re-answer the wizard.
    config["schema_version"] = CONFIG_SCHEMA_VERSION
    return config


def load_loop_config(config_path: str = "") -> dict:
    path_text = config_path or os.environ.get("CODEX_DEV_LOOP_CONFIG", "")
    path = Path(path_text).expanduser() if path_text else default_config_path()
    if not path.exists():
        config = default_config()
        config["path"] = str(path)
        config["configured"] = False
        config["home_anchored"] = False
        return config
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"codex-dev-loop config is invalid JSON: {path}: {exc}") from exc
    config = normalize_config(data)
    config["path"] = str(path)
    config["configured"] = True
    # Gate-script overrides are only honored from the home-anchored config so
    # a workspace-local JSON passed via --config cannot swap in a fake gate.
    try:
        config["home_anchored"] = path.resolve() == default_config_path().resolve()
    except OSError:
        config["home_anchored"] = False
    return config


def loop_config(state: dict) -> dict:
    return normalize_config(state.get("config", {}))


def quality_profile(state: dict) -> dict:
    return QUALITY_PROFILES[loop_config(state)["quality_profile"]]


def loop_scale(state: dict) -> str:
    scale = state.get("scale") or "standard"
    if scale not in SCALE_INDEX:
        raise SystemExit(f"Loop state has invalid scale: {scale!r}")
    return scale


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
    commands = [["diff", "--numstat"]]
    if base_ref:
        commands.insert(0, ["diff", "--numstat", f"{base_ref}...HEAD"])
        commands.insert(1, ["diff", "--numstat", f"{base_ref}..HEAD"])
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
        if total:
            return total
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
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    path = root / "loop-state.json"
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


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
    return hash_files(root, ["source.md"])


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
    roles = [REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer", "implementation-reviewer", DOCS_IMPACT_REVIEWER_ROLE, "risk-reviewer"]
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


def assert_source_ready(root: Path) -> None:
    source_path = root / "source.md"
    if not source_path.exists():
        raise SystemExit("Missing source.md; run init first.")
    source = source_path.read_text(encoding="utf-8", errors="replace")
    if not section_has_content(source, "## Goal") or not section_has_content(source, "## Acceptance Criteria"):
        raise SystemExit(
            "source.md must contain non-empty Goal and Acceptance Criteria sections. "
            "Stay in the intake phase and clarify the requirement with the user "
            "(record questions and answers in clarification-log.md) before set-phase planning."
        )


def parse_spec_delta(text: str) -> dict:
    capabilities: dict[str, dict[str, list[str]]] = {}
    current_capability = ""
    current_bucket = ""
    no_impact_lines: list[str] = []
    in_no_impact = False
    bucket_names = {"added requirements": "added", "modified requirements": "modified", "removed requirements": "removed"}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("## capability:"):
            current_capability = line.split(":", 1)[1].strip()
            current_bucket = ""
            in_no_impact = False
            if current_capability and not current_capability.startswith("<"):
                capabilities.setdefault(current_capability, {"added": [], "modified": [], "removed": []})
            continue
        if lower.startswith("## no spec impact"):
            in_no_impact = True
            current_capability = ""
            current_bucket = ""
            continue
        if lower.startswith("## "):
            in_no_impact = False
            current_capability = ""
            current_bucket = ""
            continue
        if lower.startswith("### "):
            bucket = bucket_names.get(lower[4:].strip(), "")
            current_bucket = bucket
            continue
        if lower.startswith("#### requirement:"):
            title = line.split(":", 1)[1].strip()
            if current_capability and not current_capability.startswith("<") and current_bucket and title:
                capabilities[current_capability][current_bucket].append(title)
            continue
        if in_no_impact and line and line not in {"-", "- ...", "TBD", "TODO", "N/A"}:
            no_impact_lines.append(line)
    declared = {
        name: buckets
        for name, buckets in capabilities.items()
        if any(buckets["added"]) or any(buckets["modified"]) or any(buckets["removed"])
    }
    return {"capabilities": declared, "no_impact_reason": " ".join(no_impact_lines).strip()}


def validate_delta_shape(delta: dict) -> dict:
    if delta["capabilities"] and delta["no_impact_reason"]:
        raise SystemExit("spec-delta.md is ambiguous: it declares capability requirements and a No Spec Impact reason. Keep exactly one.")
    if not delta["capabilities"] and not delta["no_impact_reason"]:
        raise SystemExit(
            "spec-delta.md must declare at least one '#### Requirement:' under a '## Capability:' section, "
            "or justify the change under '## No Spec Impact'."
        )
    return delta


def load_spec_delta(root: Path) -> dict:
    path = root / "spec-delta.md"
    if not path.exists():
        raise SystemExit("Missing required planning artifact: spec-delta.md")
    return validate_delta_shape(parse_spec_delta(path.read_text(encoding="utf-8", errors="replace")))


def spec_delta_baseline_problems(delta: dict, spec_dir: Path) -> tuple[list[str], dict]:
    """Mechanically compare a parsed spec delta against the baseline files.

    Shared by the loop's record-spec-merge and the standalone check-spec-delta:
    every ADDED/MODIFIED requirement title must be present in
    <spec_dir>/<capability>.md, every REMOVED title must be gone.
    """
    problems: list[str] = []
    merged: dict[str, dict[str, list[str]]] = {}
    for capability, buckets in delta["capabilities"].items():
        assert_safe_capability_name(capability)
        spec_path = spec_dir / f"{capability}.md"
        if not spec_path.exists():
            problems.append(f"Missing spec baseline file for capability {capability!r}: {spec_path}")
            continue
        text = spec_path.read_text(encoding="utf-8", errors="replace").lower()
        for title in [*buckets["added"], *buckets["modified"]]:
            if f"#### requirement: {title.lower()}" not in text:
                problems.append(f"{spec_path.name} is missing '#### Requirement: {title}' declared in the spec delta.")
        for title in buckets["removed"]:
            if f"#### requirement: {title.lower()}" in text:
                problems.append(f"{spec_path.name} still contains removed requirement '#### Requirement: {title}'.")
        merged[capability] = buckets
    return problems, merged


ARTIFACT_SECTION_REQUIREMENTS = {
    "technical-design.md": ["## Proposed Approach", "## File And Module Scope"],
    "test-plan.md": ["## Unit Tests", "## Static Gates"],
    "risk-analysis.md": ["## Correctness Risks", "## Architecture Risks"],
    "development-plan.md": ["## Unit dev-001", "- Objective:", "- Test gate:"],
}
# Scale controls how much prose the gate demands, never which files exist:
# small keeps the full artifact set but only requires real content in the
# design; large requires every listed section to be filled in.
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


def expected_failure_matches(log_text: str, expected: str) -> bool:
    expected = expected.strip().lower()
    if not expected:
        return True
    haystack = log_text.lower()
    if expected in haystack:
        return True
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_.-]{3,}", expected)
        if token not in EXPECTED_FAILURE_STOP_WORDS
    ]
    if not tokens:
        return False
    matches = sum(1 for token in tokens if token in haystack)
    required = max(1, (len(tokens) + 1) // 2)
    return matches >= required


def validate_red_failure(unit: str, log_path: Path, expected: str = "", status: str = "failed") -> dict:
    expected = expected.strip()
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


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    state_path = root / "loop-state.json"
    if state_path.exists() and not args.force:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        raise SystemExit(
            f"A previous dev loop exists at {root} (phase: {previous.get('phase', 'unknown')}). "
            "Archive it first (harness archive) or pass --force to overwrite its state."
        )
    root.mkdir(parents=True, exist_ok=True)
    config = load_loop_config(args.config)
    if args.source_type not in config["source_types"]:
        raise SystemExit(f"Configured source_types do not allow {args.source_type!r} sources.")
    scale = args.scale or config["default_scale"]
    if scale not in SCALE_INDEX:
        raise SystemExit(f"Unknown scale: {scale!r}; use one of: {', '.join(SCALES)}.")
    source = Path(args.source) if args.source else None
    if source and source.exists():
        shutil.copyfile(source, root / "source.md")
    elif not (root / "source.md").exists():
        if args.draft:
            (root / "source.md").write_text(DRAFT_SOURCE_TEMPLATE, encoding="utf-8")
        else:
            raise SystemExit(
                "A source spec is required. Pass --source <source.md>, create source.md first, "
                "or start a clarification-first loop with --draft."
            )

    for name, text in TEMPLATES.items():
        path = root / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")

    state = {
        "phase": "intake",
        "created_at": now(),
        "updated_at": now(),
        "config": config,
        "scale": scale,
        "source": str(source) if source else "",
        "source_type": args.source_type,
        "source_fingerprint": source_fingerprint(root),
        "reviews": {},
        "test_attempts": {},
        "quality_gate": {},
        "git": {},
        "github_actions": {},
        "blockers": [],
    }
    write_state(root, state)
    print(f"Initialized dev loop at {root} (phase: intake, scale: {scale})")
    print("Clarify Goal and Acceptance Criteria with the user, record Q&A in clarification-log.md, run requirements-reviewer, then set-phase planning.")
    return 0


def cmd_set_phase(args: argparse.Namespace) -> int:
    if args.phase not in PHASES:
        raise SystemExit(f"Unknown phase: {args.phase}")
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_config_allows_phase(state, args.phase)
    target_index = PHASE_INDEX[args.phase]
    if not run_budget_check_hook(
        root,
        workspace,
        state,
        f"before phase {args.phase}",
        include_diff=target_index >= PHASE_INDEX["implementation"],
        include_units=target_index >= PHASE_INDEX["plan_review"],
    ):
        write_state(root, state)
        return 1
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
    print(f"SOURCE_FINGERPRINT={source_fingerprint(root)}")
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
    if decision not in valid_review_decisions(role):
        expected = ", ".join(sorted(valid_review_decisions(role)))
        raise SystemExit(f"Review report has invalid or missing Decision: {src}; expected one of: {expected}")
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    validate_review_report(role, src, args.agent_id, root, workspace)
    if role == REQUIREMENTS_REVIEWER_ROLE:
        assert_phase(state, {"intake"})
    elif role == "plan-reviewer":
        assert_phase(state, {"planning", "plan_review"})
    elif role == MERGE_INTEGRATOR_ROLE:
        assert_phase(state, {"implementation"})
        if not has_worktree_evidence(state):
            raise SystemExit("merge-integrator is only recorded after one or more worktree test records exist.")
    elif role == DOCS_IMPACT_REVIEWER_ROLE:
        assert_phase(state, {"implementation_review", "risk_review"})
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot record docs-impact review before implementation-reviewer passes.")
    elif role == "implementation-reviewer":
        assert_phase(state, {"implementation", "implementation_review"})
        if not all_planned_tests_passed(root, state, workspace):
            missing = ", ".join(missing_or_failing_units(root, state, workspace))
            raise SystemExit(f"Cannot record implementation review before all planned test gates pass: {missing}")
    elif role == "risk-reviewer":
        assert_phase(state, {"implementation_review", "risk_review"})
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot record risk review before implementation-reviewer passes.")
    if not run_review_budget_hook(root, workspace, state, role):
        write_state(root, state)
        return 1
    increment_review_iteration(state, role)
    dest = root / "reviews" / f"{role}.md"
    copy_report(src, dest)
    fingerprints = evidence_fingerprint(root, workspace)
    state["reviews"][role] = {
        "decision": decision,
        "path": str(dest),
        "agent_id": args.agent_id,
        "source_fingerprint": fingerprints["source"] if role == REQUIREMENTS_REVIEWER_ROLE else "",
        "plan_fingerprint": fingerprints["plan"] if role != REQUIREMENTS_REVIEWER_ROLE else "",
        "workspace_fingerprint": fingerprints["workspace"] if role not in {REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer"} else "",
        "report_fingerprint": sha256_bytes(dest.read_bytes()),
        "recorded_at": now(),
    }
    if decision == "block" or (role not in {REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer", DOCS_IMPACT_REVIEWER_ROLE} and decision != "pass"):
        add_blocker(state, f"{role} returned {decision}")
        write_state(root, state)
        print(f"{role}: {decision}")
        return 1
    if role == DOCS_IMPACT_REVIEWER_ROLE and decision != "no-docs-needed":
        write_state(root, state)
        print(f"{role}: {decision}")
        return 1
    write_state(root, state)
    print(f"{role}: {decision}")
    return 0


def record_test_meta(
    root: Path,
    workspace: Path,
    state: dict,
    unit: str,
    meta_path: Path,
    stage: str = "green",
    run_cwd: Path | None = None,
    worktree: str = "",
    expected_failure: str = "",
) -> int:
    run_cwd = run_cwd or workspace
    meta = load_test_meta(meta_path, unit, run_cwd)
    attempts = state.setdefault("test_attempts", {}).setdefault(unit, [])
    record = {
        "status": meta["status"],
        "stage": stage,
        "command": meta["command"],
        "exit_code": meta.get("exit_code"),
        "log": meta["log_path"],
        "meta": str(meta_path),
        "plan_fingerprint": plan_fingerprint(root),
        "workspace_fingerprint": workspace_fingerprint(run_cwd),
        "recorded_at": now(),
    }
    if worktree:
        record["worktree"] = worktree
    if stage == "red":
        validation = validate_red_failure(unit, Path(meta["log_path"]), expected_failure, status=meta["status"])
        record["red_validation"] = validation
        attempts.append(record)
        write_state(root, state)
        if meta["status"] == "passed":
            print(
                f"{unit}: red-stage test PASSED before implementation. The test does not prove the missing behavior; "
                "strengthen it (or mark the unit '- TDD: regression-only' in the development plan and re-run plan review)."
            )
            return 1
        if meta["status"] != "failed":
            print(f"{unit}: red-stage run ended with {meta['status']}; fix the test harness so the red run fails cleanly.")
            return 1
        if validation["status"] != "pass":
            print(f"{unit}: red-stage failure rejected by red-test-validator ({validation['status']}): {validation['reason']}")
            return 1
        print(f"{unit}: red evidence recorded (attempt {len(attempts)}; red-test-validator pass)")
        return 0
    attempts.append(record)
    # test_failure_limit is the number of automatic retries allowed after a
    # failure: 0 blocks on the first failure, 3 blocks on the fourth
    # consecutive failure. Counting is consecutive (a pass resets it), skips
    # red-stage evidence runs, and also resets when a blocker is explicitly
    # resolved, so an early stumble does not count against a later,
    # unrelated regression.
    reset_marker = state.get("failure_counter_reset_at", "")
    consecutive_failures = 0
    for item in reversed(attempts):
        if attempt_stage(item) == "red":
            continue
        if item.get("status") == "passed":
            break
        if reset_marker and item.get("recorded_at", "") <= reset_marker:
            break
        consecutive_failures += 1
    configured_limit = loop_config(state)["max_test_retries_per_unit"]
    stop_after = configured_limit + 1
    if consecutive_failures >= stop_after and meta["status"] != "passed":
        add_blocker(
            state,
            f"{unit} test gate failed {consecutive_failures} consecutive time(s); configured retry limit is {configured_limit}",
        )
        write_state(root, state)
        print(f"{unit}: failed {consecutive_failures} consecutive time(s)")
        return 1
    if meta["status"] == "passed" and not run_scope_check_hook(root, workspace, state, f"{unit} green", run_cwd=run_cwd):
        write_state(root, state)
        print(f"{unit}: green test passed, but scope-check failed.")
        return 1
    if meta["status"] == "passed" and not run_budget_check_hook(root, workspace, state, f"{unit} green", run_cwd=run_cwd):
        write_state(root, state)
        print(f"{unit}: green test passed, but budget/time-box check failed.")
        return 1
    write_state(root, state)
    print(f"{unit}: {meta['status']} attempt {len(attempts)}")
    return 0


def resolve_test_gate_script(config: dict, caller_path: str = "") -> Path:
    """Trusted test gate scripts, in priority order: home-anchored config
    override, the automated-dev-executor companion skill, then the bundled
    fallback. Caller-supplied paths outside this set need test mode."""
    override = (config.get("test_gate_script") or "").strip() if config.get("home_anchored") else ""
    trusted: list[Path] = []
    if override:
        trusted.append(Path(override).expanduser())
    trusted.extend([default_test_gate_script(), BUNDLED_TEST_GATE_SCRIPT])
    if caller_path:
        candidate = Path(caller_path).expanduser()
        try:
            is_trusted = any(candidate.resolve() == item.resolve() for item in trusted)
        except OSError:
            is_trusted = False
        if not is_trusted:
            assert_test_mode("Caller-supplied test gate scripts")
        if not candidate.exists():
            raise SystemExit(f"Test gate script does not exist: {candidate}")
        return candidate
    for item in trusted:
        if item.exists():
            return item
    raise SystemExit(
        "No test gate script found. Install the automated-dev-executor skill, set test_gate_script in the "
        "codex-dev-loop config, or restore the bundled scripts/test_gate.py."
    )


def assert_green_stage_allowed(root: Path, state: dict, unit: str) -> None:
    if not unit_red_gate_satisfied(root, state, unit):
        raise SystemExit(
            f"Unit {unit} has no red-stage TDD evidence for the current plan. Run the test gate with --stage red "
            "against the new failing test first, or mark the unit '- TDD: regression-only' in development-plan.md "
            "before plan review."
        )


def run_test_gate(
    root: Path,
    workspace: Path,
    state: dict,
    unit: str,
    test_command: str,
    stage: str,
    timeout: int,
    script: Path,
    expected_failure: str = "",
) -> int:
    if stage == "green":
        assert_green_stage_allowed(root, state, unit)
    command = [
        sys.executable,
        str(script),
        "--unit",
        unit,
        "--command",
        test_command,
        "--cwd",
        str(workspace),
        "--timeout",
        str(timeout),
    ]
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    meta = parse_key_value_output(result.stdout, "AUTODEV_TEST_META")
    if not meta:
        raise SystemExit("Test gate did not report AUTODEV_TEST_META.")
    return record_test_meta(root, workspace, state, unit, Path(meta), stage=stage, expected_failure=expected_failure)


def cmd_run_test(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    if args.stage not in TEST_STAGES:
        raise SystemExit(f"Unknown test stage: {args.stage!r}; use red or green.")
    script = resolve_test_gate_script(loop_config(state), args.test_gate_script)
    return run_test_gate(root, workspace, state, args.unit, args.command, args.stage, args.timeout, script, expected_failure=args.expected_failure)


def is_linked_worktree(workspace: Path, candidate: Path) -> bool:
    completed = run_git(candidate, ["rev-parse", "--git-common-dir"])
    if completed.returncode != 0:
        return False
    common = Path(completed.stdout.strip())
    if not common.is_absolute():
        common = (candidate / common).resolve()
    try:
        return common.resolve() == (workspace / ".git").resolve()
    except OSError:
        return False


def cmd_record_test(args: argparse.Namespace) -> int:
    """Record a test gate run that a unit-implementer executed in an isolated
    git worktree. The orchestrator serializes these calls, so parallel units
    never race on loop-state.json. Worktree fingerprints intentionally differ
    from the main workspace: interim evidence never satisfies the final gate,
    which forces a post-merge verify-units pass in the main workspace."""
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    if args.stage not in TEST_STAGES:
        raise SystemExit(f"Unknown test stage: {args.stage!r}; use red or green.")
    worktree = Path(args.worktree).resolve()
    if not worktree.exists():
        raise SystemExit(f"Worktree does not exist: {worktree}")
    if worktree == workspace:
        raise SystemExit("record-test is for isolated worktrees; use run-test in the main workspace.")
    if not is_linked_worktree(workspace, worktree):
        raise SystemExit(f"{worktree} is not a linked git worktree of {workspace}; create it with 'git worktree add'.")
    if args.stage == "green":
        assert_green_stage_allowed(root, state, args.unit)
    return record_test_meta(
        root,
        workspace,
        state,
        args.unit,
        Path(args.meta),
        stage=args.stage,
        run_cwd=worktree,
        worktree=str(worktree),
        expected_failure=args.expected_failure,
    )


def cmd_verify_units(args: argparse.Namespace) -> int:
    """Re-run every planned unit's most recent green command in the main
    workspace. Run this after merging parallel worktrees back (and after the
    spec baseline merge), so the final per-unit evidence matches the exact
    tree that goes to review, quality gate, and PR."""
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    units = planned_units(root)
    if not units:
        raise SystemExit("development-plan.md has no '## Unit dev-*' sections to verify.")
    if has_worktree_evidence(state) and not review_is_current(state, MERGE_INTEGRATOR_ROLE, root, workspace):
        raise SystemExit("Cannot verify merged worktree units before merge-integrator passes for the current merged tree.")
    commands: dict[str, str] = {}
    missing: list[str] = []
    for unit in units:
        attempts = state.get("test_attempts", {}).get(unit, [])
        green_commands = [item.get("command") for item in attempts if attempt_stage(item) == "green" and item.get("command")]
        any_commands = [item.get("command") for item in attempts if item.get("command")]
        if green_commands:
            commands[unit] = green_commands[-1]
        elif any_commands:
            commands[unit] = any_commands[-1]
        else:
            missing.append(unit)
    if missing:
        raise SystemExit(
            "No recorded test command for unit(s): " + ", ".join(missing) + ". Run run-test or record-test for them first."
        )
    script = resolve_test_gate_script(loop_config(state), "")
    for unit in units:
        state = read_state(root)
        outcome = run_test_gate(root, workspace, state, unit, commands[unit], "green", args.timeout, script)
        if outcome != 0:
            print(f"verify-units stopped at {unit}.")
            return outcome
    print(f"verify-units: {len(units)} unit(s) re-verified in the main workspace.")
    return 0


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
        increment_quality_failure_round(state)
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
        increment_quality_failure_round(state)
        add_blocker(state, f"quality gate decision was {decision}")
        write_state(root, state)
        print("Quality gate failed")
        return 1
    write_state(root, state)
    print("Quality gate passed")
    return 0


def resolve_quality_gate_script(config: dict) -> Path:
    """Same trust ladder as the test gate: home-anchored config override,
    the ai-code-quality-gate companion skill, then the bundled fallback."""
    override = (config.get("quality_gate_script") or "").strip() if config.get("home_anchored") else ""
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend([default_quality_gate_script(), BUNDLED_QUALITY_GATE_SCRIPT])
    for item in candidates:
        if item.exists():
            return item
    raise SystemExit(
        "No quality gate script found. Install the ai-code-quality-gate skill, set quality_gate_script in the "
        "codex-dev-loop config, or restore the bundled scripts/quality_gate_fallback.py."
    )


def cmd_run_quality(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"quality_gate"})
    assert_phase_prereqs(root, state, "quality_gate", workspace)
    if not run_quality_budget_hook(root, workspace, state):
        write_state(root, state)
        return 1
    if not run_scope_check_hook(root, workspace, state, "before quality/commit"):
        write_state(root, state)
        return 1
    script = resolve_quality_gate_script(loop_config(state))
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
    state["git"]["base_commit"] = current_git_head(workspace)
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
    if not run_scope_check_hook(root, workspace, state, "before commit"):
        write_state(root, state)
        return 1
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


def assert_safe_capability_name(name: str) -> None:
    if not name:
        raise SystemExit("spec-delta.md contains an empty capability name.")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_.")
    if name.lower() != name or any(char not in allowed for char in name) or name.startswith(".") or ".." in name:
        raise SystemExit(
            f"Capability name {name!r} must be kebab-case (lowercase letters, digits, '-', '_', '.') "
            "because it maps to a spec baseline filename."
        )


def cmd_record_spec_merge(args: argparse.Namespace) -> int:
    """Verify that the reviewed spec-delta.md is reflected in the repository
    spec baseline and record it with evidence fingerprints.

    The agent performs the actual merge edit in <spec_dir>/<capability>.md;
    this command checks the result mechanically: every ADDED/MODIFIED
    '#### Requirement:' title must exist in the capability file and every
    REMOVED title must be gone. The record binds to plan and workspace
    fingerprints, so later code or spec edits invalidate it and the phase
    gates force a re-check. Because the baseline lives inside the workspace,
    spec updates ride the same branch, diff, reviews, and PR as the code."""
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    if not run_scope_check_hook(root, workspace, state, "before spec merge"):
        write_state(root, state)
        return 1
    if not run_budget_check_hook(root, workspace, state, "before spec merge"):
        write_state(root, state)
        return 1
    delta = load_spec_delta(root)
    config = loop_config(state)
    spec_dir = workspace / config["spec_dir"]
    if delta["no_impact_reason"]:
        record = {
            "status": "no-impact",
            "reason": delta["no_impact_reason"],
            "spec_dir": config["spec_dir"],
            **{f"{key}_fingerprint": value for key, value in evidence_fingerprint(root, workspace).items()},
            "recorded_at": now(),
        }
        state["spec_merge"] = record
        write_state(root, state)
        print("Spec merge recorded: no spec impact (reason kept in spec-delta.md).")
        return 0
    problems, merged = spec_delta_baseline_problems(delta, spec_dir)
    if problems:
        raise SystemExit("Spec baseline does not match spec-delta.md:\n- " + "\n- ".join(problems))
    record = {
        "status": "merged",
        "spec_dir": config["spec_dir"],
        "capabilities": merged,
        **{f"{key}_fingerprint": value for key, value in evidence_fingerprint(root, workspace).items()},
        "recorded_at": now(),
    }
    state["spec_merge"] = record
    write_state(root, state)
    total = sum(len(buckets["added"]) + len(buckets["modified"]) + len(buckets["removed"]) for buckets in merged.values())
    print(f"Spec merge recorded: {total} requirement change(s) across {len(merged)} capability file(s) in {config['spec_dir']}/.")
    return 0


def slug_for_archive(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "-" for char in value.strip())
    cleaned = cleaned.strip("-.")
    return cleaned or "run"


def cmd_archive(args: argparse.Namespace) -> int:
    """Move the finished run's records out of the working root so the next
    init starts clean and past runs stay browsable next to the spec baseline."""
    root = Path(args.root)
    state = read_state(root)
    assert_phase(state, {"complete"})
    branch = state.get("git", {}).get("branch", "")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_base = root.parent / f"{root.name}-archive"
    dest = archive_base / f"{stamp}-{slug_for_archive(branch)}"
    if dest.exists():
        raise SystemExit(f"Archive destination already exists: {dest}")
    archive_base.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root), str(dest))
    print(f"Archived dev loop records to {dest}")
    return 0


def cmd_set_scale(args: argparse.Namespace) -> int:
    root = Path(args.root)
    state = read_state(root)
    target = args.scale
    if target not in SCALE_INDEX:
        raise SystemExit(f"Unknown scale: {target!r}; use one of: {', '.join(SCALES)}.")
    current = loop_scale(state)
    if target == current:
        print(f"Scale already {current}.")
        return 0
    current_phase = phase(state)
    if SCALE_INDEX[target] < SCALE_INDEX[current] and current_phase not in {"intake", "planning"}:
        raise SystemExit(
            f"Cannot lower scale from {current} to {target} in phase {current_phase}; "
            "lowering is only allowed during intake or planning. Raising scale is allowed anytime."
        )
    state["scale"] = target
    history = state.setdefault("scale_history", [])
    history.append({"from": current, "to": target, "phase": current_phase, "at": now()})
    write_state(root, state)
    print(f"Scale set to {target} (was {current}).")
    if SCALE_INDEX[target] > SCALE_INDEX[current]:
        print("Heavier gates now apply; redo any phase gate the new scale requires (for example risk review).")
    return 0


def cmd_resolve_blocker(args: argparse.Namespace) -> int:
    """Clear recorded blockers so the loop can recover without hand-editing state.

    Every phase transition asserts there are no blockers, so without this
    command a blocked loop could never legally backtrack. Resolution requires
    a written reason, is appended to blocker-resolutions.md, and is kept as an
    auditable record in loop state. The log is intentionally a separate file:
    decision-log.md participates in the plan fingerprint, so appending there
    would invalidate every recorded review as a side effect.
    """
    root = Path(args.root)
    state = read_state(root)
    blockers = state.get("blockers") or []
    if not blockers:
        print("No blockers to resolve.")
        return 0
    reason = args.reason.strip()
    if len(reason) < 10:
        raise SystemExit("--reason must describe how the blocker was addressed (at least 10 characters).")
    resolved_at = now()
    resolutions = state.setdefault("blocker_resolutions", [])
    resolutions.append({"blockers": list(blockers), "reason": reason, "resolved_at": resolved_at})
    state["blockers"] = []
    state["failure_counter_reset_at"] = resolved_at
    resolution_log = root / "blocker-resolutions.md"
    if not resolution_log.exists():
        resolution_log.write_text("# Blocker Resolutions\n", encoding="utf-8")
    entry_lines = [f"\n## Blocker Resolution ({resolved_at})\n\n"]
    entry_lines.extend(f"- Resolved: {item}\n" for item in blockers)
    entry_lines.append(f"- Reason: {reason}\n")
    with resolution_log.open("a", encoding="utf-8") as handle:
        handle.write("".join(entry_lines))
    write_state(root, state)
    print(f"Resolved {len(blockers)} blocker(s); reason recorded in blocker-resolutions.md.")
    print("Backtrack with set-phase to redo the invalidated work before advancing again.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    automation_level = loop_config(state)["automation_level"]
    findings: list[str] = []
    try:
        assert_core_artifacts(root, loop_scale(state))
    except SystemExit as exc:
        findings.append(str(exc))
    if args.require_reviews:
        roles = required_review_roles(state, automation_level)
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


# ---------------------------------------------------------------------------
# Composable standalone mode (dev-tdd, dev-review, dev-clarify sub-skills)
#
# The state machine above is the source of truth for a full loop. Standalone
# commands let a single stage run on its own for small tasks, writing the same
# evidence format to a separate ledger so they never touch loop-state.json.
# The single-source-of-truth guard forbids standalone use while a loop is live.
# ---------------------------------------------------------------------------


def host_is_codex() -> bool:
    return not os.environ.get(HOME_ENV, "").strip()


def resolve_evidence_dir(workspace: Path, config: dict) -> Path:
    configured = (config.get("evidence_dir") or "").strip()
    if configured:
        return workspace / configured
    return workspace / DEFAULT_EVIDENCE_DIRNAME


def active_loop_state_path(workspace: Path) -> Path:
    return workspace / CANONICAL_LOOP_DIR / "loop-state.json"


def assert_no_active_loop(workspace: Path) -> None:
    path = active_loop_state_path(workspace)
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        state = {}
    current = state.get("phase", "")
    if current and current != "complete":
        raise SystemExit(
            f"An active dev loop exists at {path.parent} (phase: {current}). "
            "Standalone skills are disabled while a loop runs so evidence cannot fork; "
            "use the loop's own commands, or finish and archive the loop first."
        )


def load_ledger(path: Path, kind: str) -> dict:
    if not path.exists():
        return {"core_version": CORE_VERSION, "kind": kind, "attempts": {}, "reviews": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Evidence ledger is not valid JSON: {path}: {exc}") from exc
    data.setdefault("attempts", {})
    data.setdefault("reviews", [])
    return data


def save_ledger(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["core_version"] = CORE_VERSION
    data["updated_at"] = now()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def hash_target_paths(workspace: Path, rel_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in rel_paths:
        normalized = rel.replace("\\", "/")
        digest.update(normalized.encode("utf-8"))
        path = workspace / normalized
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def standalone_has_red(attempts: list[dict]) -> bool:
    return any(
        item.get("stage") == "red" and item.get("status") == "failed" and red_validation_allows_evidence(item)
        for item in attempts
    )


def cmd_version(args: argparse.Namespace) -> int:
    print(f"codex-dev-loop-core {CORE_VERSION}")
    if args.require:
        installed = parse_version_tuple(CORE_VERSION)
        required = parse_version_tuple(args.require)
        if installed < required:
            raise SystemExit(f"Installed core {CORE_VERSION} is older than required {args.require}.")
    return 0


def parse_version_tuple(value: str) -> tuple:
    numbers = []
    for part in value.split("-", 1)[0].split("."):
        if part.isdigit():
            numbers.append(int(part))
        else:
            break
    return tuple(numbers)


def cmd_scope_check(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not is_git_repo(workspace):
        raise SystemExit("scope-check requires a git repository.")
    root = Path(args.root)
    state: dict | None = None
    state_path = root / "loop-state.json"
    if state_path.exists():
        state = read_state(root)
    plan = Path(args.plan) if args.plan else root / "development-plan.md"
    design = Path(args.design) if args.design else root / "technical-design.md"
    result = scope_check_result(root, workspace, state=state, plan_path=plan, design_path=design, base_ref=args.base_ref)
    print_scope_check(result)
    if state is not None:
        state["scope_check"] = {**result, "context": "manual scope-check", "recorded_at": now()}
        if result["status"] != "passed" and phase(state) != "complete":
            add_blocker(state, "scope-check failed: " + "; ".join(result["findings"]))
        write_state(root, state)
    return 0 if result["status"] == "passed" else 1


def cmd_guard_check(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not is_git_repo(workspace):
        raise SystemExit("guard-check requires a git repository.")
    sensitive = sensitive_changed_paths(workspace)
    if sensitive:
        print("Sensitive paths in the current change set (escalate beyond a micro/small chain):")
        for path in sorted(sensitive):
            print(f"- {path}")
        return 1
    print("No sensitive paths in the current change set.")
    return 0


def cmd_check_spec(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"Spec file does not exist: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not section_has_content(text, "## Goal") or not section_has_content(text, "## Acceptance Criteria"):
        raise SystemExit(
            f"{path} must contain non-empty '## Goal' and '## Acceptance Criteria' sections. "
            "Keep clarifying with the user (record Q&A in a clarification log) until both are concrete."
        )
    print(f"{path}: Goal and Acceptance Criteria are present and non-empty.")
    return 0


def cmd_validate_red(args: argparse.Namespace) -> int:
    validation = validate_red_failure(args.unit, Path(args.log), args.expected, status=args.status)
    print(f"RED_TEST_VALIDATION_STATUS={validation['status']}")
    print(f"RED_TEST_VALIDATION_REASON={validation['reason']}")
    if validation.get("expected"):
        print(f"RED_TEST_VALIDATION_EXPECTED={validation['expected']}")
    return 0 if validation["status"] == "pass" else 1


def cmd_standalone_fingerprint(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    targets = split_csv(args.target)
    if not targets:
        raise SystemExit("Pass --target as a comma-separated list of workspace-relative files.")
    print(f"TARGET_FINGERPRINT={hash_target_paths(workspace, targets)}")
    return 0


def cmd_standalone_test(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = load_loop_config(args.config)
    assert_no_active_loop(workspace)
    if args.stage not in TEST_STAGES:
        raise SystemExit(f"Unknown test stage: {args.stage!r}; use red or green.")
    label = args.label.strip()
    if not label:
        raise SystemExit("Pass a non-empty --label to identify the behavior under test.")
    mode = args.mode
    if mode not in TDD_MODES:
        raise SystemExit(f"Unknown --mode {mode!r}; use red or regression-only.")
    ledger_path = resolve_evidence_dir(workspace, config) / "tdd" / "ledger.json"
    ledger = load_ledger(ledger_path, "tdd")
    attempts = ledger["attempts"].setdefault(label, [])
    # regression-only mirrors the loop's per-unit waiver: a change already
    # covered by existing tests (or a non-behavioral ship) records green
    # without a red run. Recorded honestly so the evidence shows which
    # discipline was used. The red stage is meaningless under this mode.
    if mode == "regression-only" and args.stage == "red":
        raise SystemExit("--mode regression-only has no red stage; run --stage green.")
    if mode == "red" and args.stage == "green" and not standalone_has_red(attempts):
        raise SystemExit(
            f"Green stage refused for {label!r}: no prior failing red run. "
            "Run --stage red against the new failing test first, or use --mode regression-only "
            "if existing tests already cover the change."
        )
    script = resolve_test_gate_script(config, args.test_gate_script)
    command = [
        sys.executable,
        str(script),
        "--unit",
        label,
        "--command",
        args.command,
        "--cwd",
        str(workspace),
        "--timeout",
        str(args.timeout),
    ]
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    meta_path = parse_key_value_output(result.stdout, "AUTODEV_TEST_META")
    if not meta_path:
        raise SystemExit("Test gate did not report AUTODEV_TEST_META.")
    meta = load_test_meta(Path(meta_path), label, workspace)
    record = {
        "stage": args.stage,
        "mode": mode,
        "status": meta["status"],
        "command": meta["command"],
        "exit_code": meta.get("exit_code"),
        "log": meta["log_path"],
        "meta": str(meta_path),
        "workspace_fingerprint": workspace_fingerprint(workspace),
        "recorded_at": now(),
    }
    if args.stage == "red":
        validation = validate_red_failure(label, Path(meta["log_path"]), args.expected_failure, status=meta["status"])
        record["red_validation"] = validation
        attempts.append(record)
        save_ledger(ledger_path, ledger)
        if meta["status"] == "passed":
            print(f"{label}: red-stage test PASSED before implementation; the test does not prove the missing behavior. Strengthen it.")
            return 1
        if meta["status"] != "failed":
            print(f"{label}: red-stage run ended with {meta['status']}; fix the test harness so the red run fails cleanly.")
            return 1
        if validation["status"] != "pass":
            print(f"{label}: red-stage failure rejected by red-test-validator ({validation['status']}): {validation['reason']}")
            return 1
        print(f"{label}: red evidence recorded ({ledger_path}; red-test-validator pass).")
        return 0
    attempts.append(record)
    save_ledger(ledger_path, ledger)
    if meta["status"] != "passed":
        print(f"{label}: green-stage run is {meta['status']}; keep iterating.")
        return 1
    print(f"{label}: green pass recorded ({ledger_path}).")
    return 0


def validate_standalone_review(role: str, report: Path, agent_id: str, target_fingerprint: str) -> None:
    text = report.read_text(encoding="utf-8", errors="replace")
    missing = [section for section in REVIEW_SECTIONS[role] if section.lower() not in text.lower()]
    if missing:
        raise SystemExit(f"{role} report is missing required sections: {', '.join(missing)}")
    if parse_report_field(text, "Agent ID:") != agent_id:
        raise SystemExit(f"{role} report Agent ID does not match --agent-id.")
    if parse_report_field(text, "Target Fingerprint:") != target_fingerprint:
        raise SystemExit(
            f"{role} report Target Fingerprint is stale or missing; it must echo the current TARGET_FINGERPRINT "
            "(get it from `standalone-fingerprint --target ...`)."
        )


def cmd_standalone_review(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = load_loop_config(args.config)
    assert_no_active_loop(workspace)
    role = args.role
    if role not in REVIEW_ROLES:
        raise SystemExit(f"Unknown review role: {role}")
    validate_agent_id(args.agent_id)
    targets = split_csv(args.target)
    if not targets:
        raise SystemExit("Pass --target as a comma-separated list of workspace-relative files under review.")
    src = Path(args.report)
    if not src.exists():
        raise SystemExit(f"Review report does not exist: {src}")
    decision = parse_decision(src)
    if decision not in valid_review_decisions(role):
        expected = ", ".join(sorted(valid_review_decisions(role)))
        raise SystemExit(f"Review report has invalid or missing Decision: {src}; expected one of: {expected}")
    target_fingerprint = hash_target_paths(workspace, targets)
    validate_standalone_review(role, src, args.agent_id, target_fingerprint)
    review_dir = resolve_evidence_dir(workspace, config) / "review"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = review_dir / f"{role}-{stamp}.md"
    copy_report(src, dest)
    ledger_path = review_dir / "ledger.json"
    ledger = load_ledger(ledger_path, "review")
    ledger["reviews"].append(
        {
            "role": role,
            "decision": decision,
            "targets": targets,
            "target_fingerprint": target_fingerprint,
            "agent_id": args.agent_id,
            "report": str(dest),
            "recorded_at": now(),
        }
    )
    save_ledger(ledger_path, ledger)
    print(f"{role}: {decision} (recorded to {ledger_path}).")
    return 0 if review_decision_allows_progress(role, decision) else 1


def cmd_check_spec_delta(args: argparse.Namespace) -> int:
    """Standalone spec-delta validation (dev-spec). Same mechanical check as the
    loop's record-spec-merge, but on a given delta file and spec dir, with no
    loop state. Used both after a merge edit and after bootstrap."""
    workspace = Path(args.workspace).resolve()
    delta_path = Path(args.delta)
    if not delta_path.exists():
        raise SystemExit(f"Spec delta file does not exist: {delta_path}")
    delta = validate_delta_shape(parse_spec_delta(delta_path.read_text(encoding="utf-8", errors="replace")))
    if delta["no_impact_reason"]:
        print("Spec delta declares no spec impact; nothing to reconcile against the baseline.")
        return 0
    spec_dir = workspace / args.spec_dir
    problems, merged = spec_delta_baseline_problems(delta, spec_dir)
    if problems:
        print("Spec baseline does not match the spec delta:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    total = sum(len(b["added"]) + len(b["modified"]) + len(b["removed"]) for b in merged.values())
    print(f"Spec baseline matches the delta: {total} requirement change(s) across {len(merged)} capability file(s) in {args.spec_dir}/.")
    return 0


def latest_green_attempt(ledger: dict) -> dict | None:
    latest: dict | None = None
    for attempts in ledger.get("attempts", {}).values():
        for item in attempts:
            if item.get("stage") == "green" and item.get("status") == "passed":
                if latest is None or item.get("recorded_at", "") > latest.get("recorded_at", ""):
                    latest = item
    return latest


def cmd_ship_check(args: argparse.Namespace) -> int:
    """Floor gate for dev-ship: a git repo, not on a protected branch, and a
    green test recorded against the exact tree being shipped. Standalone chains
    stay honest 鈥?you cannot open a PR without current green evidence."""
    workspace = Path(args.workspace).resolve()
    config = load_loop_config(args.config)
    assert_no_active_loop(workspace)
    if not is_git_repo(workspace):
        raise SystemExit("ship-check requires a git repository.")
    branch = current_git_branch(workspace)
    if not branch:
        raise SystemExit("ship-check requires a named branch (detached HEAD is not shippable).")
    if branch in PROTECTED_BRANCHES or branch.startswith("release/"):
        raise SystemExit(f"Refusing to ship from a protected branch: {branch}. Create a feature branch first.")
    ledger_path = resolve_evidence_dir(workspace, config) / "tdd" / "ledger.json"
    if not ledger_path.exists():
        raise SystemExit(
            "No test evidence found. Record at least one green run with standalone-test "
            "(TDD or --mode regression-only) before shipping."
        )
    ledger = load_ledger(ledger_path, "tdd")
    green = latest_green_attempt(ledger)
    if green is None:
        raise SystemExit("No green test evidence in the ledger. Record a green standalone-test run before shipping.")
    if green.get("workspace_fingerprint") != workspace_fingerprint(workspace):
        raise SystemExit(
            "The working tree changed since the last green test. Re-run standalone-test green "
            "against the current tree so the PR ships on verified-green evidence."
        )
    print(f"ship-check passed on branch {branch}: green evidence is current for the shipping tree.")
    return 0


def cmd_adopt_evidence(args: argparse.Namespace) -> int:
    """Absorb standalone dev-tdd evidence into a running loop (the upgrade path).

    When a user starts with dev-tdd and later escalates to the full loop, this
    imports each standalone green that still matches the current tree so the
    unit's test gate does not have to be re-run. Adoption is fingerprint-gated:
    a standalone green is only adopted when its workspace fingerprint equals the
    loop's current workspace fingerprint (the tree has not changed since). For a
    red-mode unit the matching failing red attempt is imported too, re-stamped
    to the current plan fingerprint, so the red-before-green gate is satisfied
    honestly. Units without a current standalone green are left for a normal run.
    """
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    config = loop_config(state)
    ledger_path = resolve_evidence_dir(workspace, config) / "tdd" / "ledger.json"
    if not ledger_path.exists():
        print(f"No standalone tdd evidence to adopt at {ledger_path}.")
        return 0
    ledger = load_ledger(ledger_path, "tdd")
    current_plan = plan_fingerprint(root)
    current_workspace = workspace_fingerprint(workspace)
    adopted: list[str] = []
    skipped: list[str] = []
    for unit in planned_units(root):
        attempts = ledger.get("attempts", {}).get(unit, [])
        green = None
        for item in attempts:
            if item.get("stage") == "green" and item.get("status") == "passed" and item.get("workspace_fingerprint") == current_workspace:
                green = item
        if green is None:
            skipped.append(unit)
            continue
        loop_attempts = state.setdefault("test_attempts", {}).setdefault(unit, [])
        if unit_tdd_mode(root, unit) == "red":
            red = next((item for item in attempts if item.get("stage") == "red" and item.get("status") == "failed"), None)
            if red is not None:
                loop_attempts.append(
                    {
                        "status": "failed",
                        "stage": "red",
                        "command": red.get("command", ""),
                        "exit_code": red.get("exit_code"),
                        "log": red.get("log", ""),
                        "meta": red.get("meta", ""),
                        "plan_fingerprint": current_plan,
                        "workspace_fingerprint": current_workspace,
                        "recorded_at": now(),
                        "red_validation": red.get("red_validation", {"status": "pass", "reason": "adopted legacy standalone red evidence."}),
                        "adopted_from": "standalone",
                    }
                )
        loop_attempts.append(
            {
                "status": "passed",
                "stage": "green",
                "command": green.get("command", ""),
                "exit_code": green.get("exit_code"),
                "log": green.get("log", ""),
                "meta": green.get("meta", ""),
                "plan_fingerprint": current_plan,
                "workspace_fingerprint": current_workspace,
                "recorded_at": now(),
                "adopted_from": "standalone",
            }
        )
        adopted.append(unit)
    write_state(root, state)
    print(f"Adopted standalone green evidence for {len(adopted)} unit(s): {', '.join(adopted) or 'none'}.")
    if skipped:
        print(f"No current standalone green for {len(skipped)} unit(s) (run their gate normally): {', '.join(skipped)}.")
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
    init.add_argument("--scale", choices=SCALES, default="", help="Task scale; defaults to default_scale from config.")
    init.add_argument("--draft", action="store_true", help="Start with a skeleton source.md and clarify Goal/Acceptance Criteria in the intake phase.")
    init.add_argument("--force", action="store_true", help="Overwrite the state of an existing (unarchived) loop.")
    init.set_defaults(func=cmd_init)

    phase = sub.add_parser("set-phase")
    phase.add_argument("phase")
    phase.set_defaults(func=cmd_set_phase)

    scale = sub.add_parser("set-scale")
    scale.add_argument("scale", choices=SCALES)
    scale.set_defaults(func=cmd_set_scale)

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
    test.add_argument("--stage", choices=sorted(TEST_STAGES), default="green", help="red records failing TDD evidence; green is the pass gate.")
    test.add_argument("--timeout", type=int, default=600)
    test.add_argument("--expected-failure", default="", help="For --stage red, text describing the intended missing behavior that should appear in the failure log.")
    test.add_argument("--test-gate-script", default="", help="Defaults to config override, companion skill, or bundled test_gate.py.")
    test.set_defaults(func=cmd_run_test)

    record_test = sub.add_parser("record-test")
    record_test.add_argument("--unit", required=True)
    record_test.add_argument("--meta", required=True, help="AUTODEV_TEST_META JSON produced by the test gate inside the worktree.")
    record_test.add_argument("--worktree", required=True, help="Linked git worktree where the unit-implementer ran the gate.")
    record_test.add_argument("--stage", choices=sorted(TEST_STAGES), default="green")
    record_test.add_argument("--expected-failure", default="", help="For --stage red, text describing the intended missing behavior that should appear in the failure log.")
    record_test.set_defaults(func=cmd_record_test)

    verify = sub.add_parser("verify-units")
    verify.add_argument("--timeout", type=int, default=600)
    verify.set_defaults(func=cmd_verify_units)

    spec_merge = sub.add_parser("record-spec-merge")
    spec_merge.set_defaults(func=cmd_record_spec_merge)

    archive = sub.add_parser("archive")
    archive.set_defaults(func=cmd_archive)

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

    resolve = sub.add_parser("resolve-blocker")
    resolve.add_argument("--reason", required=True, help="How the blocker was addressed; recorded in blocker-resolutions.md.")
    resolve.set_defaults(func=cmd_resolve_blocker)

    validate = sub.add_parser("validate")
    validate.add_argument("--require-reviews", action="store_true")
    validate.add_argument("--require-final", action="store_true")
    validate.set_defaults(func=cmd_validate)

    # Composable standalone commands (used by the dev-* sub-skills).
    version = sub.add_parser("version")
    version.add_argument("--require", default="", help="Exit non-zero if the installed core is older than this version.")
    version.set_defaults(func=cmd_version)

    scope = sub.add_parser("scope-check")
    scope.add_argument("--plan", default="", help="development-plan.md path; defaults to <root>/development-plan.md.")
    scope.add_argument("--design", default="", help="technical-design.md path; defaults to <root>/technical-design.md.")
    scope.add_argument("--base-ref", default="", help="Optional git ref to include committed branch diff in the check.")
    scope.set_defaults(func=cmd_scope_check)

    guard = sub.add_parser("guard-check")
    guard.set_defaults(func=cmd_guard_check)

    validate_red = sub.add_parser("validate-red")
    validate_red.add_argument("--unit", required=True)
    validate_red.add_argument("--log", required=True, help="Red-stage test log to inspect.")
    validate_red.add_argument("--expected", default="", help="Expected missing behavior or assertion text for the red failure.")
    validate_red.add_argument("--status", choices=["passed", "failed", "timeout", "error"], default="failed")
    validate_red.set_defaults(func=cmd_validate_red)

    check_spec = sub.add_parser("check-spec")
    check_spec.add_argument("--file", required=True, help="Spec/source file to validate for a non-empty Goal and Acceptance Criteria.")
    check_spec.set_defaults(func=cmd_check_spec)

    standalone_fp = sub.add_parser("standalone-fingerprint")
    standalone_fp.add_argument("--target", required=True, help="Comma-separated workspace-relative files to fingerprint.")
    standalone_fp.set_defaults(func=cmd_standalone_fingerprint)

    standalone_test = sub.add_parser("standalone-test")
    standalone_test.add_argument("--label", required=True, help="Identifier for the behavior under test.")
    standalone_test.add_argument("--command", required=True)
    standalone_test.add_argument("--stage", choices=sorted(TEST_STAGES), default="green")
    standalone_test.add_argument("--mode", choices=sorted(TDD_MODES), default="red", help="red enforces red-before-green; regression-only records green for changes covered by existing tests.")
    standalone_test.add_argument("--expected-failure", default="", help="For --stage red, text describing the intended missing behavior that should appear in the failure log.")
    standalone_test.add_argument("--timeout", type=int, default=600)
    standalone_test.add_argument("--test-gate-script", default="")
    standalone_test.set_defaults(func=cmd_standalone_test)

    standalone_review = sub.add_parser("standalone-review")
    standalone_review.add_argument("--role", required=True, help="One of plan-reviewer, merge-integrator, implementation-reviewer, docs-impact-reviewer, risk-reviewer.")
    standalone_review.add_argument("--report", required=True)
    standalone_review.add_argument("--agent-id", required=True)
    standalone_review.add_argument("--target", required=True, help="Comma-separated workspace-relative files under review.")
    standalone_review.set_defaults(func=cmd_standalone_review)

    check_delta = sub.add_parser("check-spec-delta")
    check_delta.add_argument("--delta", required=True, help="Spec delta file to validate against the baseline.")
    check_delta.add_argument("--spec-dir", default="specs", help="Baseline spec directory, relative to the workspace.")
    check_delta.set_defaults(func=cmd_check_spec_delta)

    ship = sub.add_parser("ship-check")
    ship.set_defaults(func=cmd_ship_check)

    adopt = sub.add_parser("adopt-evidence")
    adopt.set_defaults(func=cmd_adopt_evidence)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())





