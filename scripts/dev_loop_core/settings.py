"""Configuration, constants, profiles, and host paths for the dev-loop core."""

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
STANDALONE_REVIEW_ROLES = {"plan-reviewer", "implementation-reviewer", "risk-reviewer"}
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
GOAL_HEADINGS = ("## Goal", "## 目标")
ACCEPTANCE_HEADINGS = ("## Acceptance Criteria", "## 验收标准")


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


BUNDLED_TEST_GATE_SCRIPT = Path(__file__).resolve().parent.parent / "test_gate.py"
BUNDLED_QUALITY_GATE_SCRIPT = Path(__file__).resolve().parent.parent / "quality_gate_fallback.py"
TEST_MODE_ENV = "CODEX_DEV_LOOP_TEST_MODE"
# Standalone evidence lives inside the workspace so it stays visible to git and
# reviewers, exactly like loop evidence. The canonical loop dir is what the
# single-source-of-truth guard watches for an in-flight loop.
DEFAULT_EVIDENCE_DIRNAME = ".codex/evidence"
CANONICAL_LOOP_DIR = ".codex/dev-loop"
CONFIG_SCHEMA_VERSION = 4
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
        "require_ai_review": False,
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
    # schema <= 3 exposed risk_mode choices that never changed harness
    # behavior. Drop the legacy key instead of preserving a false promise;
    # architecture/security/data/credential/quality blockers remain hard stops.
    config.pop("risk_mode", None)
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
    # Older configs are accepted: new keys fall back to safe defaults and
    # removed non-functional keys are discarded during normalization.
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
