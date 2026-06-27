#!/usr/bin/env python3
"""Validate Codex dev loop artifact presence and review decisions."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import dev_loop_harness


REQUIRED_FILES = [
    "source.md",
    "technical-design.md",
    "test-plan.md",
    "risk-analysis.md",
    "development-plan.md",
    "decision-log.md",
]

FINAL_FILES = [
    "final-report.md",
    "pr-body.md",
    "github-actions.md",
    "quality-gate-summary.md",
]


REQUIRED_HEADINGS = {
    "technical-design.md": ["# Technical Design", "## Goal", "## Acceptance Criteria", "## Proposed Approach", "## File And Module Scope"],
    "test-plan.md": ["# Test Plan", "## Unit Tests", "## Static Gates", "## Coverage Gaps"],
    "risk-analysis.md": ["# Risk Analysis", "## Correctness Risks", "## Security Risks", "## Architecture Risks"],
    "development-plan.md": ["# Development Plan", "## Unit dev-001", "- Objective:", "- Test gate:"],
    "decision-log.md": ["# Decision Log"],
}


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Codex dev loop records.")
    parser.add_argument("--root", default=".codex/dev-loop", help="Dev loop record directory.")
    parser.add_argument("--workspace", default=".", help="Workspace directory for harness-backed validation.")
    parser.add_argument("--require-reviews", action="store_true", help="Require passing reviews appropriate to the automation level.")
    parser.add_argument("--require-final", action="store_true", help="Require final records appropriate to the automation level.")
    return parser.parse_args()


def use_harness_validation(args: argparse.Namespace, root: Path) -> int | None:
    state_path = root / "loop-state.json"
    if not state_path.exists() and not args.require_reviews and not args.require_final:
        return None
    harness_args = argparse.Namespace(
        root=str(root),
        workspace=args.workspace,
        require_reviews=args.require_reviews or args.require_final,
        require_final=args.require_final,
    )
    return dev_loop_harness.cmd_validate(harness_args)


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    harness_result = use_harness_validation(args, root)
    if harness_result is not None:
        return harness_result
    findings: list[str] = []

    if not root.exists():
        findings.append(f"Missing artifact directory: {root}")
    else:
        for name in REQUIRED_FILES:
            path = root / name
            if not path.exists():
                findings.append(f"Missing required artifact: {path}")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for heading in REQUIRED_HEADINGS.get(name, []):
                if heading not in text:
                    findings.append(f"{path} missing heading or field: {heading}")
            if name == "source.md":
                if not section_has_content(text, "## Goal") or not section_has_content(text, "## Acceptance Criteria"):
                    findings.append(f"{path} must contain non-empty Goal and Acceptance Criteria sections")
            elif name in {"technical-design.md", "test-plan.md", "risk-analysis.md"}:
                headings = [heading for heading in REQUIRED_HEADINGS.get(name, []) if heading.startswith("##")]
                if headings and not any(section_has_content(text, heading) for heading in headings):
                    findings.append(f"{path} must contain non-placeholder content")

        if args.require_final:
            for name in FINAL_FILES:
                if not (root / name).exists():
                    findings.append(f"Missing final artifact: {root / name}")
            state_path = root / "loop-state.json"
            if state_path.exists():
                import json

                state = json.loads(state_path.read_text(encoding="utf-8"))
                for role in ["plan-reviewer", "implementation-reviewer", "risk-reviewer"]:
                    if state.get("reviews", {}).get(role, {}).get("decision") != "pass":
                        findings.append(f"Missing passing review in state: {role}")
                if state.get("quality_gate", {}).get("status") != "passed":
                    findings.append("Missing passing quality gate in state.")
                if not state.get("git", {}).get("commit"):
                    findings.append("Missing commit hash in state.")
                if not state.get("git", {}).get("pr_url"):
                    findings.append("Missing PR URL in state.")
            else:
                findings.append(f"Missing loop state: {state_path}")

    if findings:
        print("Dev loop artifact validation failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Dev loop artifacts are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
