#!/usr/bin/env python3
"""Bundled fallback quality gate for codex-dev-loop.

Produces the same evidence contract as ai-code-quality-gate's quality_gate.py
(summary.md with `# AI Quality Gate Summary` and a Decision line, plus
results.json gate records with command/exit_code/log_path), so the loop can
enforce its quality phase when the companion skill is not installed. The
companion skill, when present, still takes priority; this fallback covers
lint/typecheck/test autodetection, explicit GATE=COMMAND overrides, and
subagent-alignment report validation. Hosted scanners (semgrep/codeql/sonar/
qodana) run only when a command is supplied or the tool is already on PATH.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


GATE_ORDER = [
    "lint",
    "typecheck",
    "test",
    "semgrep",
    "codeql",
    "sonar",
    "qodana",
    "subagent-alignment",
    "ai-review",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bundled quality gate fallback.")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--require", default="")
    parser.add_argument("--skip", default="")
    parser.add_argument("--command", action="append", default=[], metavar="GATE=COMMAND")
    parser.add_argument("--pr-url", default="")
    parser.add_argument("--alignment-report", default="")
    return parser.parse_args()


def split_csv(value: str) -> set[str]:
    return {part.strip().lower() for part in value.split(",") if part.strip()}


def parse_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--command must be GATE=COMMAND, got: {item}")
        gate, command = item.split("=", 1)
        gate = gate.strip().lower()
        if gate not in GATE_ORDER:
            raise SystemExit(f"Unknown gate in --command: {gate}")
        if not command.strip():
            raise SystemExit(f"Empty command for gate: {gate}")
        overrides[gate] = command.strip()
    return overrides


def npm_script(workspace: Path, script: str) -> str | None:
    package_json = workspace / "package.json"
    if not package_json.exists():
        return None
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    scripts = package.get("scripts") if isinstance(package, dict) else None
    if not isinstance(scripts, dict) or script not in scripts:
        return None
    if (workspace / "pnpm-lock.yaml").exists():
        return f"pnpm run {script}"
    if (workspace / "yarn.lock").exists():
        return f"yarn run {script}"
    return "npm test" if script == "test" else f"npm run {script}"


def detect_commands(workspace: Path) -> dict[str, str]:
    commands: dict[str, str] = {}
    for gate in ("lint", "typecheck", "test"):
        command = npm_script(workspace, gate)
        if command:
            commands[gate] = command
    if "lint" not in commands and shutil.which("ruff") and (workspace / "pyproject.toml").exists():
        commands["lint"] = "ruff check ."
    if "test" not in commands and shutil.which("pytest") and any((workspace / name).exists() for name in ("pytest.ini", "pyproject.toml", "tests")):
        commands["test"] = "pytest"
    if (workspace / "go.mod").exists():
        commands.setdefault("typecheck", "go vet ./...")
        commands.setdefault("test", "go test ./...")
    if (workspace / "Cargo.toml").exists():
        commands.setdefault("typecheck", "cargo check --all-targets")
        commands.setdefault("test", "cargo test")
    if shutil.which("semgrep"):
        commands.setdefault("semgrep", "semgrep scan --config auto .")
    return commands


def run_gate(name: str, command: str, workspace: Path, out_dir: Path, timeout: int) -> dict:
    log_path = out_dir / f"{name}.log"
    started = time.monotonic()
    result = {"gate": name, "command": command, "status": "running", "exit_code": None, "log_path": str(log_path)}
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        log_file.write(f"$ {command}\n\n")
        log_file.flush()
        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace),
                shell=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
            )
            result["exit_code"] = completed.returncode
            result["status"] = "passed" if completed.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            result["exit_code"] = 124
            result["status"] = "timeout"
            log_file.write(f"\nTimed out after {timeout} seconds.\n")
        except Exception as exc:  # noqa: BLE001 - gate must fail closed
            result["exit_code"] = 127
            result["status"] = "error"
            log_file.write(f"\nCould not start gate: {exc}\n")
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def validate_alignment(report_path: Path, out_dir: Path) -> dict:
    log_path = out_dir / "subagent-alignment.log"
    findings: list[str] = []
    if not report_path.exists():
        findings.append(f"Report does not exist: {report_path}")
    else:
        normalized = report_path.read_text(encoding="utf-8", errors="replace").lower()
        if "decision:" not in normalized:
            findings.append("Report is missing a Decision line.")
        elif "decision: pass" not in normalized:
            findings.append("Subagent alignment decision is not pass.")
        for section in ("pr objective", "diff summary", "requirement match", "test coverage", "unexpected changes", "risk summary"):
            if section not in normalized:
                findings.append(f"Report is missing section: {section}")
    lines = [f"Alignment report: {report_path}"]
    lines.extend(f"- {finding}" for finding in findings)
    lines.append("Alignment report passed validation." if not findings else "Alignment report failed validation.")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "gate": "subagent-alignment",
        "command": f"validate alignment report {report_path}",
        "status": "failed" if findings else "passed",
        "exit_code": 1 if findings else 0,
        "log_path": str(log_path),
    }


def write_summary(out_dir: Path, workspace: Path, results: list[dict], required: set[str], missing_required: list[str], decision: str) -> None:
    lines = [
        "# AI Quality Gate Summary",
        "",
        f"- Workspace: `{workspace}`",
        f"- Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "- Gate runner: codex-dev-loop bundled fallback",
        f"- Decision: `{decision}`",
        "",
        "## Gates",
        "",
        "| Gate | Required | Status | Exit | Log |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        required_label = "yes" if result["gate"] in required else "no"
        exit_code = "" if result.get("exit_code") is None else str(result["exit_code"])
        lines.append(f"| {result['gate']} | {required_label} | {result['status']} | {exit_code} | {result.get('log_path') or ''} |")
    if missing_required:
        lines.extend(["", "## Missing Required Gates", ""])
        lines.extend(f"- {gate}" for gate in missing_required)
    lines.extend(
        [
            "",
            "## Merge Recommendation",
            "",
            "Do not merge when the decision is `block`. Configure the missing gate commands "
            "(GATE=COMMAND overrides or the ai-code-quality-gate companion skill), rerun, and attach the updated summary.",
            "",
        ]
    )
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        raise SystemExit(f"Workspace does not exist: {workspace}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else workspace / ".codex" / "quality-gate" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    skip = split_csv(args.skip)
    required = split_csv(args.require)
    overrides = parse_overrides(args.command)
    commands = detect_commands(workspace)
    commands.update(overrides)
    alignment_report = None
    if args.alignment_report:
        alignment_report = Path(args.alignment_report)
        if not alignment_report.is_absolute():
            alignment_report = workspace / alignment_report

    if args.strict:
        required.update(["lint", "typecheck", "test", "semgrep", "codeql", "sonar", "qodana"])
        required.update(overrides.keys())
        if alignment_report or "subagent-alignment" in overrides:
            required.add("subagent-alignment")

    invalid = (required | skip | set(commands)) - set(GATE_ORDER)
    if invalid:
        raise SystemExit(f"Unknown gate names: {', '.join(sorted(invalid))}")

    results: list[dict] = []
    missing_required: list[str] = []
    for gate in GATE_ORDER:
        if gate in skip:
            results.append({"gate": gate, "command": "", "status": "skipped", "exit_code": None, "log_path": ""})
            continue
        command = commands.get(gate)
        if not command:
            if gate == "subagent-alignment" and alignment_report:
                results.append(validate_alignment(alignment_report, out_dir))
                continue
            status = "missing" if gate in required else "skipped"
            results.append({"gate": gate, "command": "", "status": status, "exit_code": None, "log_path": ""})
            if gate in required:
                missing_required.append(gate)
            continue
        results.append(run_gate(gate, command, workspace, out_dir, args.timeout))

    failed = [item for item in results if item["status"] in {"failed", "timeout", "error"}]
    decision = "pass"
    if failed or missing_required:
        decision = "block"
    elif any(item["gate"] in {"subagent-alignment", "ai-review"} and item["status"] == "skipped" for item in results):
        decision = "needs-human-review"

    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_summary(out_dir, workspace, results, required, missing_required, decision)

    print(f"AI quality gate evidence: {out_dir}")
    print(f"Summary: {out_dir / 'summary.md'}")
    print(f"Decision: {decision}")
    return 1 if decision == "block" else 0


if __name__ == "__main__":
    sys.exit(main())
