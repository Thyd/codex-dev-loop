#!/usr/bin/env python3
"""Self-test for codex-dev-loop artifact validation and harness gates."""

from __future__ import annotations

import atexit
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PACKAGE_ROOT / "scripts"
TEST_TMP_ROOT = PACKAGE_ROOT / ".tmp" / "self-test"


def create_test_directory(prefix: str) -> Path:
    """Create a subprocess-friendly test directory inside the repository.

    Python's TemporaryDirectory requests mode 0700. On sandboxed Windows that
    can strip the inherited ACL needed by child processes. A normal mkdir
    inherits the workspace ACL and is portable across the CI matrix.
    """

    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP_ROOT / f"{prefix}{uuid.uuid4().hex}"
    path.mkdir()
    return path


@contextmanager
def test_workspace(prefix: str):
    path = create_test_directory(prefix)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


# Imported helpers whose names start with ``test_`` are otherwise collected by
# pytest as tests in each integration module.
test_workspace.__test__ = False


def configure_test_environment() -> None:
    os.environ["CODEX_DEV_LOOP_TEST_MODE"] = "1"
    session_home = create_test_directory("codex-dev-loop-home-")
    atexit.register(shutil.rmtree, session_home, True)
    os.environ["CODEX_DEV_LOOP_HOME"] = str(session_home)


CORE_ARTIFACTS = ["source.md", "technical-design.md", "test-plan.md", "risk-analysis.md", "development-plan.md", "spec-delta.md", "decision-log.md"]
SOURCE = "# Source\n\n## Goal\n\nShip feature.\n\n## Acceptance Criteria\n\n- Works.\n"
SPEC_DELTA_NO_IMPACT = "# Spec Delta\n\n## No Spec Impact\n\nSelf-test fixture only touches app.txt; no requirement-level change.\n"
SPEC_DELTA_CAPABILITY = (
    "# Spec Delta\n\n## Capability: app-core\n\n### ADDED Requirements\n\n"
    "#### Requirement: App stores feature flag\n\nThe app records the feature state.\n\n"
    "### MODIFIED Requirements\n\n### REMOVED Requirements\n"
)
SPEC_DELTA_REMOVED = (
    "# Spec Delta\n\n## Capability: app-core\n\n### ADDED Requirements\n\n### MODIFIED Requirements\n\n"
    "### REMOVED Requirements\n\n#### Requirement: App stores feature flag\n"
)
SPEC_BASELINE_APP_CORE = "# app-core Specification\n\n#### Requirement: App stores feature flag\n\nThe app records the feature state.\n"
DEV_PLAN_TDD_RED = (
    "# Development Plan\n\n## Unit dev-001\n\n- Objective: implement feature\n- Scope: app.txt\n"
    "- Acceptance: app.txt is updated\n- Test gate: harness run-test\n- TDD: red\n- Dependencies: none\n"
    "- Status: pending\n- Evidence:\n"
)

ARTIFACTS = {
    "technical-design.md": "# Technical Design\n\n## Goal\n\nShip feature.\n\n## Acceptance Criteria\n\n- Works.\n\n## Proposed Approach\n\nImplement the smallest code path.\n\n## File And Module Scope\n\n- app.txt\n\n## Data Model Or API Changes\n\nNo changes.\n\n## Dependencies\n\nNo new dependencies.\n\n## Non-Goals\n\nNo unrelated behavior.\n\n## Open Questions\n\nNo open questions.\n",
    "test-plan.md": "# Test Plan\n\n## Unit Tests\n\nRun a unit gate for every development unit.\n\n## Integration Tests\n\nNone.\n\n## E2E Or Browser Tests\n\nNone.\n\n## Static Gates\n\nRun ai-code-quality-gate.\n\n## Manual Checks\n\nNone.\n\n## Coverage Gaps\n\nNo browser coverage needed.\n",
    "risk-analysis.md": "# Risk Analysis\n\n## Correctness Risks\n\nImplementation could miss the acceptance criteria.\n\n## Security Risks\n\nNo new security surface.\n\n## Data Or Migration Risks\n\nNo migration.\n\n## Architecture Risks\n\nKeep the change local.\n\n## Compatibility Risks\n\nNo compatibility risk.\n\n## External Service Or Credential Risks\n\nGitHub only.\n\n## Mitigations\n\nUse reviews and gates.\n",
    "development-plan.md": "# Development Plan\n\n## Unit dev-001\n\n- Objective: implement feature\n- Scope: app.txt\n- Acceptance: app.txt is updated\n- Test gate: harness run-test\n- TDD: regression-only\n- Dependencies: none\n- Status: pending\n- Evidence:\n",
    "spec-delta.md": SPEC_DELTA_NO_IMPACT,
    "decision-log.md": "# Decision Log\n\n## 2026-01-01 00:00\n\n- Decision: use local file\n- Reason: smallest test fixture\n- Alternatives: none\n- Evidence: source.md\n",
}

PLAN_REVIEW_BODY = """Decision: pass

Findings:
- ok

Required Revisions:
- none

Blocking Questions:
- none

Rationale:
- plan is clear
"""

IMPLEMENTATION_REVIEW_BODY = """Decision: pass

PR Objective:
- Ship feature.

Diff Summary:
- app.txt updated.

Requirement Match:
- Matched: acceptance criteria.
- Missing: none.
- Ambiguous: none.

Test Coverage:
- Covered: dev-001 gate.
- Missing: none.

Unexpected Changes:
- none.

Risk Summary:
- Correctness: low.
- Security: low.
- Data or migration: none.
- Maintainability: low.

Merge Recommendation:
- pass.
"""

MERGE_INTEGRATOR_REVIEW_BODY = """Decision: pass

Merged Units:
- dev-001.

Diff Interaction:
- No cross-unit interaction conflicts.

Duplicate Logic:
- None.

Shared Interface Assumptions:
- Shared interfaces are consistent.

Test Interaction:
- No order dependency.

Hidden Conflict Risks:
- No route, config, export, type, or schema conflicts.

Integration Test Recommendation:
- Existing unit re-verification is enough for this fixture.

Required Actions:
- none.
"""

DOCS_IMPACT_REVIEW_BODY = """# Docs Impact

Decision: no-docs-needed

## Required Doc Changes

- none.

## Reason

- This fixture does not change README, docs, API reference, changelog, examples, configuration docs, migration notes, or user-facing copy.
"""

DOCS_NEEDED_REVIEW_BODY = """# Docs Impact

Decision: docs-needed

## Required Doc Changes

- Update README.

## Reason

- The behavior changed and the user-facing docs have not been updated yet.
"""

RISK_REVIEW_BODY = """Decision: pass

Architecture Risk:
- low.

Security Risk:
- low.

Data Or Migration Risk:
- none.

Compatibility Risk:
- low.

External Service Or Credential Risk:
- GitHub only.

Required Actions:
- none.
"""

REQUIREMENTS_REVIEW_BODY = """Decision: pass

Requirement Quality Matrix:
- dev-001: observable, falsifiable, bounded, non-goals clear, test mapped.

Observability:
- UI/API/log/test assertion evidence is named.

Failure Conditions:
- Fails when the observable result is absent.

Boundaries:
- Inputs, outputs, exceptions, permissions, and compatibility are clear.

Non-Goals:
- Out of scope behavior is explicit.

Test Mapping:
- dev-001 maps to at least one test assertion.

Blocking Questions:
- none.
"""


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


def must(command: list[str], cwd: Path | None = None) -> None:
    result = run(command, cwd)
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit(f"Command failed: {' '.join(command)}")


def is_excluded_workspace_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in {".git", ".codex", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"} for part in parts)


def hash_files(base: Path, names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in names:
        path = base / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
    return digest.hexdigest()


def plan_fingerprint(root: Path) -> str:
    return hash_files(root, CORE_ARTIFACTS)


def source_fingerprint(root: Path) -> str:
    return hash_files(root, ["source.md", "clarification-log.md"])


def workspace_files(workspace: Path) -> list[Path]:
    completed = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], workspace)
    if completed.returncode == 0:
        items = [item for item in completed.stdout.split("\0") if item]
        return sorted((workspace / item for item in items if not is_excluded_workspace_path(item)), key=lambda path: path.relative_to(workspace).as_posix().lower())
    return []


def workspace_fingerprint(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in workspace_files(workspace):
        relative = path.relative_to(workspace).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
    return digest.hexdigest()


def quoted_python(command: str) -> str:
    return f'"{sys.executable}" -c "{command}"'


def pass_command() -> str:
    return quoted_python("print('ok')")


def fail_command() -> str:
    return quoted_python("import sys; print('intentional missing behavior'); sys.exit(1)")


def import_error_command() -> str:
    return quoted_python("import definitely_missing_codex_dev_loop_module")


def write_source(tmp: Path) -> Path:
    source = tmp / "source.md"
    source.write_text(SOURCE, encoding="utf-8")
    return source


def write_artifacts(root: Path) -> None:
    for name, text in ARTIFACTS.items():
        (root / name).write_text(text, encoding="utf-8")


def append_dev_002(root: Path) -> None:
    with (root / "development-plan.md").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## Unit dev-002\n\n"
            "- Objective: second unit\n"
            "- Scope: app.txt\n"
            "- Acceptance: still works\n"
            "- Test gate: harness run-test\n"
            "- TDD: regression-only\n"
            "- Dependencies: dev-001\n"
            "- Status: pending\n"
            "- Evidence:\n"
        )


def init_git_repo(workspace: Path, branch: str = "codex/test") -> None:
    must(["git", "init"], workspace)
    must(["git", "config", "user.email", "codex@example.invalid"], workspace)
    must(["git", "config", "user.name", "Codex Self Test"], workspace)
    must(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], workspace)
    (workspace / "app.txt").write_text("initial\n", encoding="utf-8")
    must(["git", "add", "app.txt"], workspace)
    must(["git", "commit", "-m", "init"], workspace)
    must(["git", "checkout", "-b", branch], workspace)


def init_loop(
    harness: Path,
    tmp: Path,
    config_path: Path | None = None,
    extra_init_args: list[str] | None = None,
) -> tuple[Path, Path]:
    workspace = tmp / "repo"
    workspace.mkdir()
    init_git_repo(workspace)
    root = workspace / ".codex" / "dev-loop"
    source = write_source(tmp)
    command = [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root)]
    if config_path:
        command.extend(["--config", str(config_path)])
    command.extend(["init", "--source", str(source)])
    command.extend(extra_init_args or [])
    result = run(command)
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit("Expected harness init to pass.")
    record_requirements_review(harness, workspace, root, tmp)
    to_planning = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "planning"])
    if to_planning.returncode != 0:
        print(to_planning.stdout)
        raise SystemExit("Expected intake -> planning transition to pass for a complete source.")
    write_artifacts(root)
    return workspace, root


def record_spec_merge(harness: Path, workspace: Path, root: Path) -> subprocess.CompletedProcess:
    return run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-spec-merge"])


def must_record_spec_merge(harness: Path, workspace: Path, root: Path) -> None:
    result = record_spec_merge(harness, workspace, root)
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit("Expected record-spec-merge to pass.")


def run_bundled_test_gate(unit: str, command: str, cwd: Path) -> Path:
    """Run the bundled test gate directly (as a worktree unit-implementer
    would) and return the AUTODEV_TEST_META path."""
    gate = (SCRIPTS_ROOT / "test_gate.py").resolve()
    result = run([sys.executable, str(gate), "--unit", unit, "--command", command, "--cwd", str(cwd)])
    meta = ""
    for raw_line in result.stdout.splitlines():
        if raw_line.strip().startswith("AUTODEV_TEST_META="):
            meta = raw_line.strip().split("=", 1)[1]
    if not meta:
        print(result.stdout)
        raise SystemExit("Bundled test gate did not report AUTODEV_TEST_META.")
    return Path(meta)


def review_text(role: str, agent_id: str, root: Path, workspace: Path, body: str) -> str:
    lines = [f"Agent ID: {agent_id}"]
    if role == "requirements-reviewer":
        lines.append(f"Source Fingerprint: {source_fingerprint(root)}")
    else:
        lines.append(f"Plan Fingerprint: {plan_fingerprint(root)}")
        if role != "plan-reviewer":
            lines.append(f"Workspace Fingerprint: {workspace_fingerprint(workspace)}")
    return "\n".join(lines) + "\n\n" + body


def write_review(tmp: Path, name: str, role: str, agent_id: str, root: Path, workspace: Path, body: str) -> Path:
    report = tmp / name
    report.write_text(review_text(role, agent_id, root, workspace, body), encoding="utf-8")
    return report


def record_requirements_review(harness: Path, workspace: Path, root: Path, tmp: Path, env: dict[str, str] | None = None) -> None:
    agent_id = "019f-requirements-reviewer"
    report = write_review(tmp, "requirements-review.md", "requirements-reviewer", agent_id, root, workspace, REQUIREMENTS_REVIEW_BODY)
    result = run(
        [
            sys.executable,
            str(harness),
            "--workspace",
            str(workspace),
            "--root",
            str(root),
            "record-review",
            "--role",
            "requirements-reviewer",
            "--agent-id",
            agent_id,
            "--report",
            str(report),
        ],
        env=env,
    )
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit("Expected passing requirements review to record.")


def record_plan_review(harness: Path, workspace: Path, root: Path, tmp: Path) -> None:
    agent_id = "019f-plan-reviewer"
    report = write_review(tmp, "plan-review.md", "plan-reviewer", agent_id, root, workspace, PLAN_REVIEW_BODY)
    result = run(
        [
            sys.executable,
            str(harness),
            "--workspace",
            str(workspace),
            "--root",
            str(root),
            "record-review",
            "--role",
            "plan-reviewer",
            "--agent-id",
            agent_id,
            "--report",
            str(report),
        ]
    )
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit("Expected passing plan review to record.")


def run_test(harness: Path, workspace: Path, root: Path, unit: str, command: str, stage: str = "") -> subprocess.CompletedProcess:
    invocation = [
        sys.executable,
        str(harness),
        "--workspace",
        str(workspace),
        "--root",
        str(root),
        "run-test",
        "--unit",
        unit,
        "--command",
        command,
    ]
    if stage:
        invocation.extend(["--stage", stage])
    if stage == "red":
        invocation.extend(["--expected-failure", "intentional missing behavior"])
    return run(invocation)


def record_review(harness: Path, workspace: Path, root: Path, tmp: Path, role: str, body: str) -> subprocess.CompletedProcess:
    agent_id = "019f-" + role
    report = write_review(tmp, f"{role}.md", role, agent_id, root, workspace, body)
    return run(
        [
            sys.executable,
            str(harness),
            "--workspace",
            str(workspace),
            "--root",
            str(root),
            "record-review",
            "--role",
            role,
            "--agent-id",
            agent_id,
            "--report",
            str(report),
        ]
    )


def record_docs_impact(harness: Path, workspace: Path, root: Path, tmp: Path) -> subprocess.CompletedProcess:
    return record_review(harness, workspace, root, tmp, "docs-impact-reviewer", DOCS_IMPACT_REVIEW_BODY)


def run_quality(
    harness: Path,
    workspace: Path,
    root: Path,
    out_dir: Path,
    env: dict[str, str] | None = None,
    require: str = "",
    gate_names: list[str] | None = None,
) -> subprocess.CompletedProcess:
    # The harness resolves the quality gate script itself (companion skill or
    # bundled fallback); the self-test stays hermetic either way.
    alignment = workspace / ".codex" / "quality-gate" / "subagent-alignment.md"
    alignment.parent.mkdir(parents=True, exist_ok=True)
    alignment.write_text(IMPLEMENTATION_REVIEW_BODY, encoding="utf-8")
    command = [
        sys.executable,
        str(harness),
        "--workspace",
        str(workspace),
        "--root",
        str(root),
        "run-quality",
        "--out-dir",
        str(out_dir),
    ]
    if require:
        command.extend(["--require", require])
    for gate in gate_names or ["lint", "typecheck", "test", "semgrep", "codeql", "sonar", "qodana"]:
        command.extend(["--command", f"{gate}={pass_command()}"])
    return run(command, env=env)


def run_failing_quality(harness: Path, workspace: Path, root: Path, out_dir: Path) -> subprocess.CompletedProcess:
    alignment = workspace / ".codex" / "quality-gate" / "subagent-alignment.md"
    alignment.parent.mkdir(parents=True, exist_ok=True)
    alignment.write_text(IMPLEMENTATION_REVIEW_BODY, encoding="utf-8")
    command = [
        sys.executable,
        str(harness),
        "--workspace",
        str(workspace),
        "--root",
        str(root),
        "run-quality",
        "--out-dir",
        str(out_dir),
        "--command",
        f"lint={fail_command()}",
    ]
    for gate in ["typecheck", "test", "semgrep", "codeql", "sonar", "qodana"]:
        command.extend(["--command", f"{gate}={pass_command()}"])
    return run(command)


def write_prefilled_quality_dir(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "fake.log"
    log.write_text("fake\n", encoding="utf-8")
    summary = out_dir / "summary.md"
    summary.write_text("# AI Quality Gate Summary\n\n- Decision: `pass`\n", encoding="utf-8")
    results = []
    for gate in ["lint", "typecheck", "test", "semgrep", "codeql", "sonar", "qodana", "subagent-alignment"]:
        results.append({"gate": gate, "status": "passed", "exit_code": 0, "command": "fake", "log_path": str(log)})
    (out_dir / "results.json").write_text(json.dumps(results), encoding="utf-8")


def write_fake_codex_home(tmp: Path) -> tuple[Path, Path]:
    fake_home = tmp / "fake-codex-home"
    script = fake_home / "skills" / "ai-code-quality-gate" / "scripts" / "quality_gate.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    marker = tmp / "fake-quality-script-ran.txt"
    script.write_text(
        "from pathlib import Path\n"
        "import argparse, json\n"
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--out-dir', required=True)\n"
        "parser.add_argument('--workspace')\n"
        "parser.add_argument('--strict', action='store_true')\n"
        "parser.add_argument('--alignment-report')\n"
        "parser.add_argument('--timeout')\n"
        "parser.add_argument('--command', action='append', default=[])\n"
        "args = parser.parse_args()\n"
        "out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)\n"
        "log = out / 'fake.log'; log.write_text('fake', encoding='utf-8')\n"
        "gates = ['lint','typecheck','test','semgrep','codeql','sonar','qodana','subagent-alignment']\n"
        "(out / 'summary.md').write_text('# AI Quality Gate Summary\\n\\n- Decision: `pass`\\n', encoding='utf-8')\n"
        "(out / 'results.json').write_text(json.dumps([{'gate': g, 'status': 'passed', 'exit_code': 0, 'command': 'fake', 'log_path': str(log)} for g in gates]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return fake_home, marker
