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


CORE_ARTIFACTS = ["source.md", "technical-design.md", "test-plan.md", "risk-analysis.md", "development-plan.md", "decision-log.md"]
SOURCE = "# Source\n\n## Goal\n\nShip feature.\n\n## Acceptance Criteria\n\n- Works.\n"

ARTIFACTS = {
    "technical-design.md": "# Technical Design\n\n## Goal\n\nShip feature.\n\n## Acceptance Criteria\n\n- Works.\n\n## Proposed Approach\n\nImplement the smallest code path.\n\n## File And Module Scope\n\n- app.txt\n",
    "test-plan.md": "# Test Plan\n\n## Unit Tests\n\nRun a unit gate for every development unit.\n\n## Integration Tests\n\nNone.\n\n## E2E Or Browser Tests\n\nNone.\n\n## Static Gates\n\nRun ai-code-quality-gate.\n\n## Manual Checks\n\nNone.\n\n## Coverage Gaps\n\nNo browser coverage needed.\n",
    "risk-analysis.md": "# Risk Analysis\n\n## Correctness Risks\n\nImplementation could miss the acceptance criteria.\n\n## Security Risks\n\nNo new security surface.\n\n## Data Or Migration Risks\n\nNo migration.\n\n## Architecture Risks\n\nKeep the change local.\n\n## Compatibility Risks\n\nNo compatibility risk.\n\n## External Service Or Credential Risks\n\nGitHub only.\n\n## Mitigations\n\nUse reviews and gates.\n",
    "development-plan.md": "# Development Plan\n\n## Unit dev-001\n\n- Objective: implement feature\n- Scope: app.txt\n- Acceptance: app.txt is updated\n- Test gate: harness run-test\n- Dependencies: none\n- Status: pending\n- Evidence:\n",
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
            "- Dependencies: dev-001\n"
            "- Status: pending\n"
            "- Evidence:\n"
        )


def init_git_repo(workspace: Path, branch: str = "codex/test") -> None:
    must(["git", "init"], workspace)
    must(["git", "config", "user.email", "codex@example.invalid"], workspace)
    must(["git", "config", "user.name", "Codex Self Test"], workspace)
    (workspace / "app.txt").write_text("initial\n", encoding="utf-8")
    must(["git", "add", "app.txt"], workspace)
    must(["git", "commit", "-m", "init"], workspace)
    must(["git", "checkout", "-b", branch], workspace)


def init_loop(harness: Path, tmp: Path) -> tuple[Path, Path]:
    workspace = tmp / "repo"
    workspace.mkdir()
    init_git_repo(workspace)
    root = workspace / ".codex" / "dev-loop"
    source = write_source(tmp)
    result = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "init", "--source", str(source)])
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit("Expected harness init to pass.")
    write_artifacts(root)
    return workspace, root


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


def run_test(harness: Path, workspace: Path, root: Path, unit: str, command: str) -> subprocess.CompletedProcess:
    return run(
        [
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
    )


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


def run_quality(harness: Path, workspace: Path, root: Path, out_dir: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    quality_script = Path.home() / ".codex" / "skills" / "ai-code-quality-gate" / "scripts" / "quality_gate.py"
    if not quality_script.exists():
        raise SystemExit(f"Missing ai-code-quality-gate script for self-test: {quality_script}")
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
    for gate in ["lint", "typecheck", "test", "semgrep", "codeql", "sonar", "qodana"]:
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
    validator = Path(__file__).with_name("validate_dev_loop_artifacts.py").resolve()
    harness = Path(__file__).with_name("dev_loop_harness.py").resolve()
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
        if failed is None or failed.returncode == 0:
            print(failed.stdout if failed else "")
            print("Expected third failed test attempt to block.")
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
            json.dumps({"url": pr_url, "headRefName": "codex/test", "headRefOid": commit, "state": "OPEN"}),
            encoding="utf-8",
        )
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
        bad_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(bad_cloud_evidence), "--allow-local-simulation"])
        if bad_cloud.returncode == 0:
            print(bad_cloud.stdout)
            print("Expected incomplete cloud checks to fail.")
            return 1
        cloud_evidence = tmp / "cloud-evidence.json"
        cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "ai-quality-gate", "state": "success"},
                    {"name": "semgrep", "state": "success"},
                    {"name": "codeql", "state": "success"},
                    {"name": "sonar", "state": "success"},
                    {"name": "qodana", "state": "success"},
                    {"name": "subagent-alignment", "state": "success"},
                    {"name": "qodo-pr-agent", "state": "success"},
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

    print("codex-dev-loop self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
