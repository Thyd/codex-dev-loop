#!/usr/bin/env python3
"""Self-test for codex-dev-loop artifact validation and harness gates."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


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
    "technical-design.md": "# Technical Design\n\n## Goal\n\nShip feature.\n\n## Acceptance Criteria\n\n- Works.\n\n## Proposed Approach\n\nImplement the smallest code path.\n\n## File And Module Scope\n\n- app.txt\n",
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
    return quoted_python("import sys; sys.exit(1)")


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
    gate = Path(__file__).with_name("test_gate.py").resolve()
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
    lines = [f"Agent ID: {agent_id}", f"Plan Fingerprint: {plan_fingerprint(root)}"]
    if role != "plan-reviewer":
        lines.append(f"Workspace Fingerprint: {workspace_fingerprint(workspace)}")
    return "\n".join(lines) + "\n\n" + body


def write_review(tmp: Path, name: str, role: str, agent_id: str, root: Path, workspace: Path, body: str) -> Path:
    report = tmp / name
    report.write_text(review_text(role, agent_id, root, workspace, body), encoding="utf-8")
    return report


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


def main() -> int:
    os.environ["CODEX_DEV_LOOP_TEST_MODE"] = "1"
    # Point the loop home at an empty directory so every scenario exercises
    # the bundled gate fallbacks; the self-test must pass on machines without
    # the companion skills installed. Resolution priority gets its own test.
    session_home = Path(tempfile.mkdtemp(prefix="codex-dev-loop-home-"))
    os.environ["CODEX_DEV_LOOP_HOME"] = str(session_home)
    configurator = Path(__file__).with_name("configure_dev_loop.py").resolve()
    validator = Path(__file__).with_name("validate_dev_loop_artifacts.py").resolve()
    harness = Path(__file__).with_name("dev_loop_harness.py").resolve()
    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-config-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "codex-dev-loop.json"
        configured = run([sys.executable, str(configurator), "--non-interactive", "--output", str(config_path)])
        if configured.returncode != 0:
            print(configured.stdout)
            print("Expected configure_dev_loop.py to write default config.")
            return 1
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if data.get("automation_level") != "pr_without_merge" or data.get("quality_profile") != "standard" or data.get("test_failure_limit") != 3:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("Expected default first-run config values.")
            return 1
        if data.get("schema_version") != 2 or data.get("default_scale") != "standard" or data.get("spec_dir") != "specs":
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("Expected schema v2 defaults from the configuration wizard.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-self-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        root = tmp / ".codex" / "dev-loop"
        root.mkdir(parents=True)
        (root / "source.md").write_text(SOURCE, encoding="utf-8")
        write_artifacts(root)

        ok = run([sys.executable, str(validator), "--root", str(root)])
        if ok.returncode != 0:
            print(ok.stdout)
            print("Expected complete artifacts to pass.")
            return 1

        (root / "test-plan.md").unlink()
        missing = run([sys.executable, str(validator), "--root", str(root)])
        if missing.returncode == 0:
            print(missing.stdout)
            print("Expected missing test-plan.md to fail.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-harness-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)

        no_source = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(tmp / "bad-root"), "init"])
        if no_source.returncode == 0:
            print(no_source.stdout)
            print("Expected init without source to fail.")
            return 1

        jump = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if jump.returncode == 0:
            print(jump.stdout)
            print("Expected direct jump to complete to fail.")
            return 1

        to_plan_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if to_plan_review.returncode != 0:
            print(to_plan_review.stdout)
            print("Expected transition to plan_review to pass.")
            return 1

        synthetic = tmp / "bad-review.md"
        synthetic.write_text("Decision: pass\n", encoding="utf-8")
        bad_review = run(
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
                "019f-plan-reviewer",
                "--report",
                str(synthetic),
            ]
        )
        if bad_review.returncode == 0:
            print(bad_review.stdout)
            print("Expected review without provenance and required sections to fail.")
            return 1

        record_plan_review(harness, workspace, root, tmp)
        (root / "technical-design.md").write_text(ARTIFACTS["technical-design.md"] + "\nExtra change.\n", encoding="utf-8")
        stale_plan = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        if stale_plan.returncode == 0:
            print(stale_plan.stdout)
            print("Expected changed planning artifact to stale the plan review.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-planning-only-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "planning-only.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "planning_only",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        complete_planning_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if complete_planning_only.returncode != 0:
            print(complete_planning_only.stdout)
            print("Expected planning_only automation config to allow completion after plan review.")
            return 1
        validate_planning_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "validate", "--require-reviews", "--require-final"])
        if validate_planning_only.returncode != 0:
            print(validate_planning_only.stdout)
            print("Expected planning_only final validation to require only planning records.")
            return 1
        wrapper_validate_planning_only = run([sys.executable, str(validator), "--workspace", str(workspace), "--root", str(root), "--require-final"])
        if wrapper_validate_planning_only.returncode != 0:
            print(wrapper_validate_planning_only.stdout)
            print("Expected legacy validator to reuse planning_only harness final validation.")
            return 1
        blocked_by_config = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        if blocked_by_config.returncode == 0:
            print(blocked_by_config.stdout)
            print("Expected planning_only automation config to block branch phase.")
            return 1
        archived = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "archive"])
        if archived.returncode != 0:
            print(archived.stdout)
            print("Expected archive to move the completed loop records.")
            return 1
        if (root / "loop-state.json").exists():
            print("Expected archive to move loop-state.json out of the working root.")
            return 1
        archive_base = root.parent / f"{root.name}-archive"
        archived_runs = list(archive_base.glob("*/loop-state.json"))
        if len(archived_runs) != 1:
            print(f"Expected exactly one archived run under {archive_base}.")
            return 1
        source = write_source(tmp)
        fresh_init = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "--config", str(config_path), "init", "--source", str(source)]
        )
        if fresh_init.returncode != 0:
            print(fresh_init.stdout)
            print("Expected init to start cleanly after archive without --force.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-source-type-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        source = write_source(tmp)
        config_path = tmp / "markdown-only.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown"],
                    "quality_profile": "standard",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        blocked_source = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(workspace / ".codex" / "dev-loop"),
                "--config",
                str(config_path),
                "init",
                "--source",
                str(source),
                "--source-type",
                "notion",
            ]
        )
        if blocked_source.returncode == 0:
            print(blocked_source.stdout)
            print("Expected source_types config to block disallowed Notion source intake.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-failures-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        failed = None
        for _ in range(3):
            failed = run_test(harness, workspace, root, "dev-001", fail_command())
        if failed is None or failed.returncode != 0:
            print(failed.stdout if failed else "")
            print("Expected three failures to stay within the default retry limit of 3.")
            return 1
        failed = run_test(harness, workspace, root, "dev-001", fail_command())
        if failed.returncode == 0:
            print(failed.stdout)
            print("Expected the fourth consecutive failure to exceed the retry limit and block.")
            return 1
        blocked_test = run_test(harness, workspace, root, "dev-001", fail_command())
        if blocked_test.returncode == 0:
            print(blocked_test.stdout)
            print("Expected run-test to be rejected while the loop is blocked.")
            return 1
        no_reason = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "resolve-blocker", "--reason", "short"])
        if no_reason.returncode == 0:
            print(no_reason.stdout)
            print("Expected resolve-blocker to reject a trivial reason.")
            return 1
        resolved = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "resolve-blocker",
                "--reason",
                "Fixed the failing dependency pin so the unit test can run again.",
            ]
        )
        if resolved.returncode != 0:
            print(resolved.stdout)
            print("Expected resolve-blocker to clear the blocker with a written reason.")
            return 1
        if not (root / "blocker-resolutions.md").exists():
            print("Expected resolve-blocker to append to blocker-resolutions.md.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if state_data.get("blockers"):
            print("Expected blockers to be empty after resolve-blocker.")
            return 1
        if not state_data.get("blocker_resolutions"):
            print("Expected blocker_resolutions to be recorded in state.")
            return 1
        after_resolve = run_test(harness, workspace, root, "dev-001", fail_command())
        if after_resolve.returncode != 0:
            print(after_resolve.stdout)
            print("Expected the failure counter to reset after resolve-blocker.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-intake-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        root = workspace / ".codex" / "dev-loop"
        base = [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root)]
        drafted = run([*base, "init", "--draft"])
        if drafted.returncode != 0:
            print(drafted.stdout)
            print("Expected init --draft to start a clarification-first loop.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if state_data.get("phase") != "intake":
            print("Expected init to start in the intake phase.")
            return 1
        if not (root / "clarification-log.md").exists():
            print("Expected init to create clarification-log.md.")
            return 1
        unclear = run([*base, "set-phase", "planning"])
        if unclear.returncode == 0:
            print(unclear.stdout)
            print("Expected planning to be blocked while Goal and Acceptance Criteria are empty.")
            return 1
        (root / "source.md").write_text(SOURCE, encoding="utf-8")
        clarified = run([*base, "set-phase", "planning"])
        if clarified.returncode != 0:
            print(clarified.stdout)
            print("Expected planning to open once the clarified source has Goal and Acceptance Criteria.")
            return 1
        reinit = run([*base, "init", "--draft"])
        if reinit.returncode == 0:
            print(reinit.stdout)
            print("Expected init to refuse overwriting an unarchived loop without --force.")
            return 1
        back_to_intake = run([*base, "set-phase", "intake"])
        if back_to_intake.returncode != 0:
            print(back_to_intake.stdout)
            print("Expected planning -> intake backtrack for re-clarification.")
            return 1
        forced = run([*base, "init", "--draft", "--force"])
        if forced.returncode != 0:
            print(forced.stdout)
            print("Expected init --force to restart the loop state.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-tdd-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED.replace("- TDD: red", "- TDD: bogus"), encoding="utf-8")
        invalid_mode = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if invalid_mode.returncode == 0:
            print(invalid_mode.stdout)
            print("Expected invalid '- TDD:' value to fail artifact validation.")
            return 1
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED, encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        green_without_red = run_test(harness, workspace, root, "dev-001", pass_command())
        if green_without_red.returncode == 0:
            print(green_without_red.stdout)
            print("Expected the green stage to be rejected before red-stage TDD evidence exists.")
            return 1
        red_that_passes = run_test(harness, workspace, root, "dev-001", pass_command(), stage="red")
        if red_that_passes.returncode == 0:
            print(red_that_passes.stdout)
            print("Expected a red-stage run that passes to be flagged as not proving the behavior.")
            return 1
        still_no_green = run_test(harness, workspace, root, "dev-001", pass_command())
        if still_no_green.returncode == 0:
            print(still_no_green.stdout)
            print("Expected an unexpectedly-passing red run to not unlock the green stage.")
            return 1
        red = run_test(harness, workspace, root, "dev-001", fail_command(), stage="red")
        if red.returncode != 0:
            print(red.stdout)
            print("Expected a failing red-stage run to record TDD evidence.")
            return 1
        (workspace / "app.txt").write_text("tdd feature\n", encoding="utf-8")
        green = run_test(harness, workspace, root, "dev-001", pass_command())
        if green.returncode != 0:
            print(green.stdout)
            print("Expected the green stage to pass after red evidence exists.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        to_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if to_review.returncode != 0:
            print(to_review.stdout)
            print("Expected implementation_review to open after red evidence, green pass, and spec merge.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-worktree-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED, encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        worktree = tmp / "wt-dev-001"
        must(["git", "worktree", "add", str(worktree), "-b", "codex/wt-dev-001"], workspace)
        not_a_worktree = tmp / "plain-dir"
        not_a_worktree.mkdir()
        red_meta = run_bundled_test_gate("dev-001", fail_command(), worktree)
        rejected = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-test", "--unit", "dev-001", "--meta", str(red_meta), "--worktree", str(not_a_worktree)]
        )
        if rejected.returncode == 0:
            print(rejected.stdout)
            print("Expected record-test to reject a directory that is not a linked worktree.")
            return 1
        recorded_red = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-test", "--unit", "dev-001", "--meta", str(red_meta), "--worktree", str(worktree), "--stage", "red"]
        )
        if recorded_red.returncode != 0:
            print(recorded_red.stdout)
            print("Expected record-test to record red evidence from the worktree.")
            return 1
        (worktree / "app.txt").write_text("worktree feature\n", encoding="utf-8")
        must(["git", "add", "app.txt"], worktree)
        must(["git", "commit", "-m", "feat: unit dev-001"], worktree)
        green_meta = run_bundled_test_gate("dev-001", pass_command(), worktree)
        recorded_green = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-test", "--unit", "dev-001", "--meta", str(green_meta), "--worktree", str(worktree)]
        )
        if recorded_green.returncode != 0:
            print(recorded_green.stdout)
            print("Expected record-test to record green evidence from the worktree.")
            return 1
        must(["git", "merge", "--no-edit", "codex/wt-dev-001"], workspace)
        (workspace / "app.txt").write_text("worktree feature\nintegration tweak\n", encoding="utf-8")
        stale_worktree_green = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if stale_worktree_green.returncode == 0:
            print(stale_worktree_green.stdout)
            print("Expected interim worktree evidence to not satisfy the final gate after the main tree diverged.")
            return 1
        verified = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "verify-units"])
        if verified.returncode != 0:
            print(verified.stdout)
            print("Expected verify-units to re-run every unit gate in the main workspace.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        to_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if to_review.returncode != 0:
            print(to_review.stdout)
            print("Expected implementation_review to open after verify-units and spec merge.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-spec-merge-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        ambiguous = SPEC_DELTA_CAPABILITY + "\n## No Spec Impact\n\nAlso claiming no impact.\n"
        (root / "spec-delta.md").write_text(ambiguous, encoding="utf-8")
        ambiguous_check = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if ambiguous_check.returncode == 0:
            print(ambiguous_check.stdout)
            print("Expected an ambiguous spec-delta (capability changes plus no-impact) to fail validation.")
            return 1
        (root / "spec-delta.md").write_text(SPEC_DELTA_CAPABILITY, encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        missing_baseline = record_spec_merge(harness, workspace, root)
        if missing_baseline.returncode == 0:
            print(missing_baseline.stdout)
            print("Expected record-spec-merge to fail while the capability baseline file is missing.")
            return 1
        specs_dir = workspace / "specs"
        specs_dir.mkdir()
        (specs_dir / "app-core.md").write_text(SPEC_BASELINE_APP_CORE, encoding="utf-8")
        (workspace / "app.txt").write_text("spec feature\n", encoding="utf-8")
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        to_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if to_review.returncode != 0:
            print(to_review.stdout)
            print("Expected implementation_review to open after the spec baseline merge.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        (root / "spec-delta.md").write_text(SPEC_DELTA_REMOVED, encoding="utf-8")
        removed_still_present = record_spec_merge(harness, workspace, root)
        if removed_still_present.returncode == 0:
            print(removed_still_present.stdout)
            print("Expected record-spec-merge to fail while a REMOVED requirement is still in the baseline.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-scale-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp, extra_init_args=["--scale", "small"])
        (root / "test-plan.md").write_text("# Test Plan\n\n## Unit Tests\n\n## Integration Tests\n\n## E2E Or Browser Tests\n\n## Static Gates\n\n## Manual Checks\n\n## Coverage Gaps\n", encoding="utf-8")
        (root / "risk-analysis.md").write_text("# Risk Analysis\n\n## Correctness Risks\n\n## Security Risks\n\n## Data Or Migration Risks\n\n## Architecture Risks\n\n## Compatibility Risks\n\n## External Service Or Credential Risks\n\n## Mitigations\n", encoding="utf-8")
        relaxed = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if relaxed.returncode != 0:
            print(relaxed.stdout)
            print("Expected small scale to accept condensed test-plan and risk-analysis artifacts.")
            return 1
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("small feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        skip_clean = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        if skip_clean.returncode != 0:
            print(skip_clean.stdout)
            print("Expected small scale to skip risk_review for a non-sensitive change set.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-scale-guard-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp, extra_init_args=["--scale", "small"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("guarded feature\n", encoding="utf-8")
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        guarded = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        if guarded.returncode == 0:
            print(guarded.stdout)
            print("Expected the sensitive-path guard to refuse the small-scale risk_review skip.")
            return 1
        raised = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-scale", "standard"])
        if raised.returncode != 0:
            print(raised.stdout)
            print("Expected raising scale to be allowed at any phase.")
            return 1
        lowered = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-scale", "small"])
        if lowered.returncode == 0:
            print(lowered.stdout)
            print("Expected lowering scale after planning to be refused.")
            return 1
        to_risk = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        if to_risk.returncode != 0:
            print(to_risk.stdout)
            print("Expected risk_review to open at standard scale with full artifacts.")
            return 1
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        risk_path = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        if risk_path.returncode != 0:
            print(risk_path.stdout)
            print("Expected quality_gate to open after a real risk review at standard scale.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-config-migration-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        v1_config = tmp / "v1.json"
        v1_config.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown"],
                    "quality_profile": "standard",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=v1_config)
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        migrated = state_data.get("config", {})
        if migrated.get("schema_version") != 2 or migrated.get("default_scale") != "standard" or migrated.get("spec_dir") != "specs":
            print(json.dumps(migrated, indent=2))
            print("Expected schema v1 config to migrate to v2 defaults at init.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-gate-resolution-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        priority_home = tmp / "loop-home"
        companion = priority_home / "skills" / "automated-dev-executor" / "scripts" / "test_gate.py"
        companion.parent.mkdir(parents=True)
        companion_marker = tmp / "companion-ran.txt"
        bundled_gate = Path(__file__).with_name("test_gate.py").resolve()
        companion.write_text(
            "import runpy, sys\nfrom pathlib import Path\n"
            f"Path({str(companion_marker)!r}).write_text('ran', encoding='utf-8')\n"
            f"sys.argv[0] = {str(bundled_gate)!r}\n"
            f"runpy.run_path({str(bundled_gate)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        env = {**os.environ, "CODEX_DEV_LOOP_HOME": str(priority_home)}
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        root = workspace / ".codex" / "dev-loop"
        source = write_source(tmp)
        base = [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root)]
        for step in (
            [*base, "init", "--source", str(source)],
            [*base, "set-phase", "planning"],
        ):
            result = run(step, env=env)
            if result.returncode != 0:
                print(result.stdout)
                print("Expected gate-resolution loop setup to pass.")
                return 1
        write_artifacts(root)
        for step in ([*base, "set-phase", "plan_review"],):
            result = run(step, env=env)
            if result.returncode != 0:
                print(result.stdout)
                return 1
        agent_id = "019f-plan-reviewer"
        report = write_review(tmp, "plan-review.md", "plan-reviewer", agent_id, root, workspace, PLAN_REVIEW_BODY)
        result = run([*base, "record-review", "--role", "plan-reviewer", "--agent-id", agent_id, "--report", str(report)], env=env)
        if result.returncode != 0:
            print(result.stdout)
            return 1
        for step in (
            [*base, "set-phase", "branch"],
            [*base, "record-branch", "--branch", "codex/test"],
            [*base, "set-phase", "implementation"],
        ):
            result = run(step, env=env)
            if result.returncode != 0:
                print(result.stdout)
                return 1
        gate_run = run([*base, "run-test", "--unit", "dev-001", "--command", pass_command()], env=env)
        if gate_run.returncode != 0:
            print(gate_run.stdout)
            print("Expected run-test to pass via the relocated companion test gate.")
            return 1
        if not companion_marker.exists():
            print("Expected the companion skill test gate under CODEX_DEV_LOOP_HOME to take priority over the bundled fallback.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-all-units-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        append_dev_002(root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        run_test(harness, workspace, root, "dev-002", fail_command())
        blocked = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if blocked.returncode == 0:
            print(blocked.stdout)
            print("Expected implementation_review transition to fail until every planned unit passes.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-quality-failure-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        blocked_without_spec_merge = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if blocked_without_spec_merge.returncode == 0:
            print(blocked_without_spec_merge.stdout)
            print("Expected implementation_review transition to require record-spec-merge.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        failing_quality = run_failing_quality(harness, workspace, root, tmp / "failing-quality")
        if failing_quality.returncode == 0:
            print(failing_quality.stdout)
            print("Expected failing ai-code-quality-gate process to block.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-quality-floor-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        reduced_quality = run_quality(harness, workspace, root, tmp / "reduced-quality", require="test", gate_names=["test"])
        if reduced_quality.returncode == 0:
            print(reduced_quality.stdout)
            print("Expected --require test to add to, not replace, configured standard quality gates.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-commit-only-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "commit-only.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "commit_only",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "light",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("commit-only feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        quality = run_quality(harness, workspace, root, tmp / "commit-only-quality")
        if quality.returncode != 0:
            print(quality.stdout)
            print("Expected commit_only quality gate to pass.")
            return 1
        must(["git", "add", "app.txt"], workspace)
        must(["git", "commit", "-m", "feat: commit-only feature"], workspace)
        record_commit = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-commit"])
        if record_commit.returncode != 0:
            print(record_commit.stdout)
            print("Expected record-commit to pass after quality gate and git commit.")
            return 1
        complete_commit_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if complete_commit_only.returncode != 0:
            print(complete_commit_only.stdout)
            print("Expected commit_only automation config to allow completion after recorded commit.")
            return 1
        validate_commit_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "validate", "--require-reviews", "--require-final"])
        if validate_commit_only.returncode != 0:
            print(validate_commit_only.stdout)
            print("Expected commit_only final validation to require commit but not PR/cloud records.")
            return 1
        wrapper_validate_commit_only = run([sys.executable, str(validator), "--workspace", str(workspace), "--root", str(root), "--require-final"])
        if wrapper_validate_commit_only.returncode != 0:
            print(wrapper_validate_commit_only.stdout)
            print("Expected legacy validator to reuse commit_only harness final validation.")
            return 1
        blocked_pr = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "pr"])
        if blocked_pr.returncode == 0:
            print(blocked_pr.stdout)
            print("Expected commit_only automation config to block PR phase.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-happy-path-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())

        (workspace / "app.txt").write_text("feature changed after test\n", encoding="utf-8")
        stale_test = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if stale_test.returncode == 0:
            print(stale_test.stdout)
            print("Expected code changes after tests to stale test evidence.")
            return 1
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            print("Expected implementation review to record.")
            return 1

        (workspace / "app.txt").write_text("feature changed after implementation review\n", encoding="utf-8")
        stale_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        if stale_review.returncode == 0:
            print(stale_review.stdout)
            print("Expected code changes after implementation review to stale review evidence.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            print("Expected risk review to record.")
            return 1

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        fake_quality_script = tmp / "fake-quality-gate.py"
        fake_quality_script.write_text("print('fake')\n", encoding="utf-8")
        fake_script_attempt = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "run-quality",
                "--quality-gate-script",
                str(fake_quality_script),
                "--out-dir",
                str(tmp / "fake-script-quality"),
            ]
        )
        if fake_script_attempt.returncode == 0:
            print(fake_script_attempt.stdout)
            print("Expected caller-supplied quality gate script to be rejected.")
            return 1
        old_record_quality = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-quality"])
        if old_record_quality.returncode == 0:
            print(old_record_quality.stdout)
            print("Expected removed record-quality command to fail.")
            return 1
        stale_quality_dir = tmp / "prefilled-quality"
        write_prefilled_quality_dir(stale_quality_dir)
        stale_quality = run_quality(harness, workspace, root, stale_quality_dir)
        if stale_quality.returncode == 0:
            print(stale_quality.stdout)
            print("Expected run-quality to reject pre-existing out-dir artifacts.")
            return 1
        fake_home, fake_marker = write_fake_codex_home(tmp)
        fake_env = {**os.environ, "CODEX_HOME": str(fake_home)}
        quality = run_quality(harness, workspace, root, tmp / "quality-run", env=fake_env)
        if quality.returncode != 0:
            print(quality.stdout)
            print("Expected real ai-code-quality-gate run to pass even when CODEX_HOME is fake.")
            return 1
        if fake_marker.exists():
            print("Expected run-quality to ignore CODEX_HOME fake quality gate script.")
            return 1

        must(["git", "add", "app.txt"], workspace)
        must(["git", "commit", "-m", "feat: self-test feature"], workspace)
        commit = run(["git", "rev-parse", "HEAD"], workspace).stdout.strip()

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "pr"])
        pr_url = "https://github.com/example/repo/pull/1"
        pr_evidence = tmp / "pr-evidence.json"
        pr_evidence.write_text(
            json.dumps({"url": pr_url, "headRefName": "codex/test", "headRefOid": commit, "state": "OPEN", "baseRepository": {"nameWithOwner": "example/repo"}}),
            encoding="utf-8",
        )
        production_env = {**os.environ}
        production_env.pop("CODEX_DEV_LOOP_TEST_MODE", None)
        simulated_pr_without_test_mode = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                commit,
                "--pr-url",
                pr_url,
                "--evidence",
                str(pr_evidence),
                "--allow-local-simulation",
            ],
            env=production_env,
        )
        if simulated_pr_without_test_mode.returncode == 0:
            print(simulated_pr_without_test_mode.stdout)
            print("Expected local PR simulation to be rejected outside CODEX_DEV_LOOP_TEST_MODE.")
            return 1
        bad_pr = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                "badcommit",
                "--pr-url",
                pr_url,
                "--evidence",
                str(pr_evidence),
                "--allow-local-simulation",
            ]
        )
        if bad_pr.returncode == 0:
            print(bad_pr.stdout)
            print("Expected PR record with wrong commit to fail.")
            return 1
        wrong_repo_pr_evidence = tmp / "wrong-repo-pr-evidence.json"
        wrong_repo_pr_evidence.write_text(
            json.dumps(
                {
                    "url": "https://github.com/example/other/pull/1",
                    "headRefName": "codex/test",
                    "headRefOid": commit,
                    "state": "OPEN",
                    "baseRepository": {"nameWithOwner": "example/other"},
                }
            ),
            encoding="utf-8",
        )
        wrong_repo_pr = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                commit,
                "--pr-url",
                "https://github.com/example/other/pull/1",
                "--evidence",
                str(wrong_repo_pr_evidence),
                "--allow-local-simulation",
            ]
        )
        if wrong_repo_pr.returncode == 0:
            print(wrong_repo_pr.stdout)
            print("Expected PR evidence for a different GitHub repository to fail.")
            return 1
        pr = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                commit,
                "--pr-url",
                pr_url,
                "--evidence",
                str(pr_evidence),
                "--allow-local-simulation",
            ]
        )
        if pr.returncode != 0:
            print(pr.stdout)
            print("Expected PR record to pass.")
            return 1

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "cloud_checks"])
        bad_cloud_evidence = tmp / "bad-cloud-evidence.json"
        bad_cloud_evidence.write_text(json.dumps([{"name": "ai-quality-gate", "state": "success"}]), encoding="utf-8")
        simulated_cloud_without_test_mode = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-cloud",
                "--status",
                "passed",
                "--evidence",
                str(bad_cloud_evidence),
                "--allow-local-simulation",
            ],
            env=production_env,
        )
        if simulated_cloud_without_test_mode.returncode == 0:
            print(simulated_cloud_without_test_mode.stdout)
            print("Expected local cloud simulation to be rejected outside CODEX_DEV_LOOP_TEST_MODE.")
            return 1
        bad_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(bad_cloud_evidence), "--allow-local-simulation"])
        if bad_cloud.returncode == 0:
            print(bad_cloud.stdout)
            print("Expected incomplete cloud checks to fail.")
            return 1
        completed_cloud_evidence = tmp / "completed-cloud-evidence.json"
        completed_cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "ai-quality-gate", "state": "completed"},
                    {"name": "qodo-pr-agent", "state": "success"},
                ]
            ),
            encoding="utf-8",
        )
        completed_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(completed_cloud_evidence), "--allow-local-simulation"])
        if completed_cloud.returncode == 0:
            print(completed_cloud.stdout)
            print("Expected completed-without-success cloud check state to fail.")
            return 1
        substring_cloud_evidence = tmp / "substring-cloud-evidence.json"
        substring_cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "not-ai-quality-gate", "state": "success"},
                    {"name": "qodo-pr-agent", "state": "success"},
                ]
            ),
            encoding="utf-8",
        )
        substring_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(substring_cloud_evidence), "--allow-local-simulation"])
        if substring_cloud.returncode == 0:
            print(substring_cloud.stdout)
            print("Expected cloud checks to require exact canonical names, not substring matches.")
            return 1
        cloud_evidence = tmp / "cloud-evidence.json"
        cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "ai-quality-gate", "state": "success"},
                    {"name": "Semgrep OSS Scan", "state": "success"},
                    {"name": "CodeQL", "state": "success"},
                    {"name": "SonarCloud Code Analysis", "state": "success"},
                    {"name": "Qodana Scan", "state": "success"},
                    {"name": "subagent-alignment", "state": "success"},
                    {"name": "qodo-pr-agent", "state": "success"},
                    {"name": "optional-flaky-check", "state": "failure"},
                ]
            ),
            encoding="utf-8",
        )
        cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(cloud_evidence), "--allow-local-simulation"])
        if cloud.returncode != 0:
            print(cloud.stdout)
            print("Expected cloud checks to pass.")
            return 1

        complete = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if complete.returncode != 0:
            print(complete.stdout)
            print("Expected transition to complete to pass after all prerequisites.")
            return 1

        back = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        if back.returncode != 0:
            print(back.stdout)
            print("Expected backtrack to implementation to pass.")
            return 1
        stale_after_backtrack = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if stale_after_backtrack.returncode == 0:
            print(stale_after_backtrack.stdout)
            print("Expected backtrack to clear stale test evidence before implementation review.")
            return 1

    if standalone_tests() != 0:
        return 1

    print("codex-dev-loop self-test passed")
    return 0


def standalone(harness: Path, workspace: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return run([sys.executable, str(harness), "--workspace", str(workspace), *args], env=env)


def standalone_tests() -> int:
    """P1 composable standalone mode: guard-check, check-spec, standalone TDD,
    standalone review, the single-source-of-truth guard, and version handshake."""
    harness = Path(__file__).with_name("dev_loop_harness.py").resolve()

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-standalone-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)

        # version handshake
        ok_version = standalone(harness, workspace, "version", "--require", "0.5.0")
        if ok_version.returncode != 0:
            print(ok_version.stdout)
            print("Expected the installed core to satisfy a 0.5.0 requirement.")
            return 1
        too_new = standalone(harness, workspace, "version", "--require", "99.0.0")
        if too_new.returncode == 0:
            print(too_new.stdout)
            print("Expected version --require to reject an impossible future version.")
            return 1

        # guard-check clean vs sensitive
        clean_guard = standalone(harness, workspace, "guard-check")
        if clean_guard.returncode != 0:
            print(clean_guard.stdout)
            print("Expected guard-check to pass on a non-sensitive change set.")
            return 1
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        dirty_guard = standalone(harness, workspace, "guard-check")
        if dirty_guard.returncode == 0:
            print(dirty_guard.stdout)
            print("Expected guard-check to flag a dependency manifest change.")
            return 1
        (workspace / "package.json").unlink()

        # check-spec fail then pass
        spec = workspace / "spec.md"
        spec.write_text("# Spec\n\n## Goal\n\n## Acceptance Criteria\n", encoding="utf-8")
        empty_spec = standalone(harness, workspace, "check-spec", "--file", str(spec))
        if empty_spec.returncode == 0:
            print(empty_spec.stdout)
            print("Expected check-spec to reject empty Goal/Acceptance Criteria.")
            return 1
        spec.write_text(SOURCE, encoding="utf-8")
        good_spec = standalone(harness, workspace, "check-spec", "--file", str(spec))
        if good_spec.returncode != 0:
            print(good_spec.stdout)
            print("Expected check-spec to accept a filled-in spec.")
            return 1

        # standalone TDD: green refused without red, then red -> green
        green_first = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "green", "--command", pass_command())
        if green_first.returncode == 0:
            print(green_first.stdout)
            print("Expected standalone green stage to be refused before red evidence exists.")
            return 1
        red = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "red", "--command", fail_command())
        if red.returncode != 0:
            print(red.stdout)
            print("Expected a failing standalone red run to record evidence.")
            return 1
        red_that_passes = standalone(harness, workspace, "standalone-test", "--label", "other", "--stage", "red", "--command", pass_command())
        if red_that_passes.returncode == 0:
            print(red_that_passes.stdout)
            print("Expected a passing red run to be flagged as not proving the behavior.")
            return 1
        green = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "green", "--command", pass_command())
        if green.returncode != 0:
            print(green.stdout)
            print("Expected standalone green stage to pass after red evidence exists.")
            return 1
        ledger = json.loads((workspace / ".codex" / "evidence" / "tdd" / "ledger.json").read_text(encoding="utf-8"))
        if [item["stage"] for item in ledger["attempts"]["feat"]] != ["red", "green"]:
            print(json.dumps(ledger, indent=2))
            print("Expected the tdd ledger to record red then green for the label.")
            return 1

        # standalone review bound to a target fingerprint
        (workspace / "target.txt").write_text("v1\n", encoding="utf-8")
        fp_out = standalone(harness, workspace, "standalone-fingerprint", "--target", "target.txt")
        fingerprint = ""
        for line in fp_out.stdout.splitlines():
            if line.strip().startswith("TARGET_FINGERPRINT="):
                fingerprint = line.strip().split("=", 1)[1]
        if not fingerprint:
            print(fp_out.stdout)
            print("Expected standalone-fingerprint to print TARGET_FINGERPRINT.")
            return 1
        report = tmp / "review.md"
        report.write_text(
            f"Agent ID: 019f-standalone-reviewer\nTarget Fingerprint: {fingerprint}\n\n" + IMPLEMENTATION_REVIEW_BODY,
            encoding="utf-8",
        )
        recorded = standalone(
            harness, workspace, "standalone-review",
            "--role", "implementation-reviewer", "--agent-id", "019f-standalone-reviewer",
            "--report", str(report), "--target", "target.txt",
        )
        if recorded.returncode != 0:
            print(recorded.stdout)
            print("Expected a passing standalone review with a current fingerprint to record.")
            return 1
        (workspace / "target.txt").write_text("v2 changed\n", encoding="utf-8")
        stale = standalone(
            harness, workspace, "standalone-review",
            "--role", "implementation-reviewer", "--agent-id", "019f-standalone-reviewer",
            "--report", str(report), "--target", "target.txt",
        )
        if stale.returncode == 0:
            print(stale.stdout)
            print("Expected a standalone review to go stale after the target changed.")
            return 1

        # single-source-of-truth guard: an active loop disables standalone
        loop_dir = workspace / ".codex" / "dev-loop"
        loop_dir.mkdir(parents=True, exist_ok=True)
        (loop_dir / "loop-state.json").write_text(json.dumps({"phase": "implementation"}), encoding="utf-8")
        blocked = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "red", "--command", fail_command())
        if blocked.returncode == 0:
            print(blocked.stdout)
            print("Expected standalone commands to be refused while a loop is active.")
            return 1
        guard_still_ok = standalone(harness, workspace, "guard-check")
        if guard_still_ok.returncode not in (0, 1):
            print(guard_still_ok.stdout)
            print("Expected guard-check to remain usable regardless of loop state.")
            return 1
        (loop_dir / "loop-state.json").write_text(json.dumps({"phase": "complete"}), encoding="utf-8")
        allowed = standalone(harness, workspace, "standalone-test", "--label", "feat2", "--stage", "red", "--command", fail_command())
        if allowed.returncode != 0:
            print(allowed.stdout)
            print("Expected standalone commands to resume once the loop is complete.")
            return 1

    if standalone_ship_and_spec_tests() != 0:
        return 1

    if standalone_upgrade_path_test() != 0:
        return 1

    return 0


def standalone_upgrade_path_test() -> int:
    """The escalation story: a user runs dev-tdd standalone, then upgrades to
    the full loop; adopt-evidence absorbs the fingerprint-current green so the
    unit gate is satisfied without re-running the test."""
    harness = Path(__file__).with_name("dev_loop_harness.py").resolve()

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-upgrade-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)  # app.txt committed, on branch codex/test
        root = workspace / ".codex" / "dev-loop"

        def hp(*args: str) -> subprocess.CompletedProcess:
            return run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), *args])

        # 1) Standalone dev-tdd for a unit named dev-001 (no loop exists yet).
        red = standalone(harness, workspace, "standalone-test", "--label", "dev-001", "--stage", "red", "--command", fail_command())
        if red.returncode != 0:
            print(red.stdout)
            print("Expected standalone red to record before the loop exists.")
            return 1
        green = standalone(harness, workspace, "standalone-test", "--label", "dev-001", "--stage", "green", "--command", pass_command())
        if green.returncode != 0:
            print(green.stdout)
            print("Expected standalone green to record before the loop exists.")
            return 1

        # 2) Escalate: start the full loop in the same workspace.
        source = write_source(tmp)
        if hp("init", "--source", str(source)).returncode != 0:
            print("Expected loop init to succeed on the escalation path.")
            return 1
        if hp("set-phase", "planning").returncode != 0:
            print("Expected intake -> planning to succeed.")
            return 1
        write_artifacts(root)
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED, encoding="utf-8")
        hp("set-phase", "plan_review")
        record_plan_review(harness, workspace, root, tmp)
        hp("set-phase", "branch")
        hp("record-branch", "--branch", "codex/test")
        hp("set-phase", "implementation")

        # 3) Adopt the standalone evidence; the unit gate should then be met
        #    without any loop run-test.
        adopt = hp("adopt-evidence")
        if adopt.returncode != 0 or "dev-001" not in adopt.stdout:
            print(adopt.stdout)
            print("Expected adopt-evidence to adopt the standalone green for dev-001.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        advanced = hp("set-phase", "implementation_review")
        if advanced.returncode != 0:
            print(advanced.stdout)
            print("Expected the adopted red+green evidence to satisfy the unit gate.")
            return 1

        # 4) A tree change after adoption must stale the adopted green.
        hp("set-phase", "implementation")
        (workspace / "app.txt").write_text("changed after adoption\n", encoding="utf-8")
        stale = hp("set-phase", "implementation_review")
        if stale.returncode == 0:
            print(stale.stdout)
            print("Expected a post-adoption tree change to stale the adopted evidence.")
            return 1

    return 0


def standalone_ship_and_spec_tests() -> int:
    """P2 composable commands: regression-only TDD mode, ship-check floor gate,
    and standalone check-spec-delta."""
    harness = Path(__file__).with_name("dev_loop_harness.py").resolve()

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-ship-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)  # leaves HEAD on branch "codex/test"

        # ship-check with no green evidence is refused.
        no_evidence = standalone(harness, workspace, "ship-check")
        if no_evidence.returncode == 0:
            print(no_evidence.stdout)
            print("Expected ship-check to refuse without any green test evidence.")
            return 1

        # regression-only green needs no prior red.
        reg = standalone(harness, workspace, "standalone-test", "--label", "ship", "--mode", "regression-only", "--stage", "green", "--command", pass_command())
        if reg.returncode != 0:
            print(reg.stdout)
            print("Expected regression-only green to record without a red run.")
            return 1
        reg_red = standalone(harness, workspace, "standalone-test", "--label", "ship", "--mode", "regression-only", "--stage", "red", "--command", fail_command())
        if reg_red.returncode == 0:
            print(reg_red.stdout)
            print("Expected regression-only mode to reject a red stage.")
            return 1

        # ship-check now passes on the current tree.
        ok_ship = standalone(harness, workspace, "ship-check")
        if ok_ship.returncode != 0:
            print(ok_ship.stdout)
            print("Expected ship-check to pass with current green evidence on a feature branch.")
            return 1

        # changing the tree invalidates the green evidence.
        (workspace / "app.txt").write_text("shipped change\n", encoding="utf-8")
        stale_ship = standalone(harness, workspace, "ship-check")
        if stale_ship.returncode == 0:
            print(stale_ship.stdout)
            print("Expected ship-check to go stale after the working tree changed.")
            return 1

        # protected branch is refused.
        must(["git", "add", "-A"], workspace)
        must(["git", "commit", "-m", "wip"], workspace)
        must(["git", "checkout", "master"], workspace)
        protected = standalone(harness, workspace, "ship-check")
        if protected.returncode == 0:
            print(protected.stdout)
            print("Expected ship-check to refuse a protected branch.")
            return 1

    with tempfile.TemporaryDirectory(prefix="codex-dev-loop-checkdelta-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        (workspace / "specs").mkdir()
        delta = workspace / "spec-delta.md"
        delta.write_text(
            "# Spec Delta\n\n## Capability: app-core\n\n### ADDED Requirements\n\n#### Requirement: Stores flag\n\nThe app records the flag.\n",
            encoding="utf-8",
        )
        missing_baseline = standalone(harness, workspace, "check-spec-delta", "--delta", str(delta), "--spec-dir", "specs")
        if missing_baseline.returncode == 0:
            print(missing_baseline.stdout)
            print("Expected check-spec-delta to fail while the baseline file is missing.")
            return 1
        (workspace / "specs" / "app-core.md").write_text(
            "# app-core Specification\n\n#### Requirement: Stores flag\n\nThe app records the flag.\n", encoding="utf-8"
        )
        matched = standalone(harness, workspace, "check-spec-delta", "--delta", str(delta), "--spec-dir", "specs")
        if matched.returncode != 0:
            print(matched.stdout)
            print("Expected check-spec-delta to pass once the baseline contains the requirement.")
            return 1
        no_impact = workspace / "delta2.md"
        no_impact.write_text("# Spec Delta\n\n## No Spec Impact\n\nDocs only.\n", encoding="utf-8")
        ni = standalone(harness, workspace, "check-spec-delta", "--delta", str(no_impact), "--spec-dir", "specs")
        if ni.returncode != 0:
            print(ni.stdout)
            print("Expected a No Spec Impact delta to pass check-spec-delta.")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
