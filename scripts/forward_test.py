#!/usr/bin/env python3
"""Prepare and evaluate disposable, fresh-agent forward-test cases."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Scenario:
    name: str
    automation_level: str
    scale: str
    request: str
    files: dict[str, str]


@dataclass(frozen=True)
class PreparedCase:
    name: str
    root: Path
    repo: Path
    home: Path
    request: Path
    prompt: str


@dataclass(frozen=True)
class EvaluationResult:
    case: str
    passed: bool
    evidence_path: Path | None
    problems: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "passed": self.passed,
            "evidence_path": str(self.evidence_path) if self.evidence_path else "",
            "problems": list(self.problems),
        }


SCENARIOS = {
    "planning": Scenario(
        name="planning",
        automation_level="planning_only",
        scale="standard",
        request="""
            # Catalog CSV Export

            ## Goal

            Design a repository change that adds CSV export for the existing
            in-memory catalog without changing the current catalog query API.

            ## Acceptance Criteria

            - Given catalog rows with `name`, `category`, and integer `quantity`,
              exporting produces UTF-8 CSV with the header
              `name,category,quantity` in that order.
            - Fields containing commas, quotes, or newlines follow standard CSV
              quoting; embedded quotes are escaped correctly.
            - Export preserves input row order and ends with exactly one newline.
            - An empty catalog exports only the header and one trailing newline.
            - The plan maps each behavior to an automated test and names the
              expected files or modules to change.

            ## Constraints

            - Use the Python standard library only.
            - Keep the public `list_items()` behavior unchanged.
            - This run is planning-only; do not edit production code or tests.

            ## Non-Goals

            - Importing CSV.
            - File upload/download UI.
            - Changing catalog storage or sorting.
        """,
        files={
            "catalog.py": """
                from __future__ import annotations


                def list_items(rows: list[dict[str, object]]) -> list[dict[str, object]]:
                    return list(rows)
            """,
            "test_catalog.py": """
                from __future__ import annotations

                import unittest

                from catalog import list_items


                class CatalogTests(unittest.TestCase):
                    def test_list_items_preserves_order(self) -> None:
                        rows = [{"name": "A"}, {"name": "B"}]
                        self.assertEqual(list_items(rows), rows)


                if __name__ == "__main__":
                    unittest.main()
            """,
        },
    ),
    "commit": Scenario(
        name="commit",
        automation_level="commit_only",
        scale="small",
        request="""
            # Normalize Slugs

            ## Goal

            Extend the existing `slugify` behavior so user-entered titles become
            stable, URL-friendly ASCII slugs.

            ## Acceptance Criteria

            - `slugify(" Hello,   World! ")` returns `"hello-world"`.
            - Any consecutive non-alphanumeric characters produce at most one
              hyphen.
            - Leading and trailing separators are removed.
            - Existing ASCII letters are lowercased and digits are preserved.
            - Empty input, or input containing no ASCII letters or digits, returns
              an empty string.
            - Automated tests cover punctuation, repeated separators, digits, and
              empty output.

            ## Constraints

            - Use the Python standard library only.
            - Keep the public function name and one-string-argument signature
              unchanged.
            - Run the configured full development loop through its commit-only
              boundary.

            ## Non-Goals

            - Transliteration of non-ASCII text.
            - Custom replacement characters.
            - Publishing or opening a pull request.
        """,
        files={
            "slugger.py": """
                from __future__ import annotations


                def slugify(value: str) -> str:
                    return value.lower().replace(" ", "-")
            """,
            "test_slugger.py": """
                from __future__ import annotations

                import unittest

                from slugger import slugify


                class SlugifyTests(unittest.TestCase):
                    def test_lowercases_simple_words(self) -> None:
                        self.assertEqual(slugify("Hello World"), "hello-world")


                if __name__ == "__main__":
                    unittest.main()
            """,
        },
    ),
}


def _clean_block(value: str) -> str:
    return textwrap.dedent(value).strip() + "\n"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _scenario(case: str) -> Scenario:
    try:
        return SCENARIOS[case]
    except KeyError as exc:
        choices = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"unknown forward-test case {case!r}; choose {choices}") from exc


def prepare_case(case: str, output_root: Path, skill_dir: Path) -> PreparedCase:
    """Create a clean repo, task-local home, and neutral fresh-agent prompt."""

    scenario = _scenario(case)
    output_root = output_root.resolve()
    skill_dir = skill_dir.resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise FileNotFoundError(f"skill entrypoint not found: {skill_dir / 'SKILL.md'}")
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"forward-test output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    repo = output_root / "repo"
    home = output_root / "home"
    config_dir = home / "config"
    repo.mkdir()
    config_dir.mkdir(parents=True)

    request = repo / "request.md"
    request.write_text(_clean_block(scenario.request), encoding="utf-8")
    for relative, content in scenario.files.items():
        (repo / relative).write_text(_clean_block(content), encoding="utf-8")

    config = {
        "schema_version": 4,
        "automation_level": scenario.automation_level,
        "source_types": ["markdown"],
        "quality_profile": "light",
        "test_failure_limit": 2,
        "default_scale": scenario.scale,
        "spec_dir": "specs",
        "evidence_dir": "",
    }
    (config_dir / "codex-dev-loop.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )

    _git(repo, "init", "-q")
    _git(repo, "branch", "-M", "main")
    _git(repo, "config", "user.name", "Codex Forward Test")
    _git(repo, "config", "user.email", "forward-test@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "forward-test fixture baseline")

    prompt = (
        f"Use $codex-dev-loop at {skill_dir / 'SKILL.md'} to handle {request} "
        f"in repo {repo}. Use task-local {home} as CODEX_DEV_LOOP_HOME for every "
        "harness command. Follow the configured automation boundary and work "
        "normally. Return a concise outcome with evidence paths."
    )
    (output_root / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    return PreparedCase(scenario.name, output_root, repo, home, request, prompt)


def _load_json(path: Path, problems: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"cannot read evidence state {path}: {exc}")
        return None
    if not isinstance(value, dict):
        problems.append(f"evidence state is not a JSON object: {path}")
        return None
    return value


def _latest_archive_state(repo: Path) -> Path | None:
    archive_root = repo / ".codex" / "dev-loop-archive"
    if not archive_root.is_dir():
        return None
    candidates = sorted(archive_root.glob("*/loop-state.json"), key=lambda path: path.parent.name)
    return candidates[-1] if candidates else None


def _review_problems(state: dict[str, Any], roles: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    reviews = state.get("reviews")
    if not isinstance(reviews, dict):
        return ["reviews evidence is missing"]
    agent_ids: list[str] = []
    for role, accepted in roles.items():
        record = reviews.get(role)
        if not isinstance(record, dict):
            problems.append(f"required review is missing: {role}")
            continue
        if record.get("decision") not in accepted:
            problems.append(f"{role} has unacceptable decision: {record.get('decision')!r}")
        agent_id = record.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            problems.append(f"{role} has no fresh agent identity")
        else:
            agent_ids.append(agent_id)
    if len(agent_ids) != len(set(agent_ids)):
        problems.append("required reviews reuse an agent identity")
    return problems


def _non_evidence_changes(repo: Path) -> list[str]:
    completed = _git(repo, "status", "--porcelain", "--untracked-files=all", check=False)
    if completed.returncode != 0:
        return ["<git status failed>"]
    changes: list[str] = []
    for line in completed.stdout.splitlines():
        raw_path = line[3:].strip().strip('"') if len(line) > 3 else ""
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[-1]
        normalized = raw_path.replace("\\", "/")
        if normalized.startswith(".codex/"):
            continue
        if normalized.endswith(".pyc") or "/__pycache__/" in f"/{normalized}":
            continue
        changes.append(normalized or line)
    return changes


def _tdd_problems(state: dict[str, Any]) -> list[str]:
    attempts_by_unit = state.get("test_attempts")
    if not isinstance(attempts_by_unit, dict) or not attempts_by_unit:
        return ["commit case has no TDD attempts"]
    problems: list[str] = []
    for unit, attempts in attempts_by_unit.items():
        if not isinstance(attempts, list):
            problems.append(f"{unit} test attempts are malformed")
            continue
        valid_red = next(
            (
                index
                for index, attempt in enumerate(attempts)
                if isinstance(attempt, dict)
                and attempt.get("stage") == "red"
                and attempt.get("status") == "failed"
                and attempt.get("exit_code") not in (None, 0)
                and isinstance(attempt.get("red_validation"), dict)
                and attempt["red_validation"].get("status") == "pass"
            ),
            None,
        )
        valid_green = next(
            (
                index
                for index, attempt in enumerate(attempts)
                if isinstance(attempt, dict)
                and attempt.get("stage") == "green"
                and attempt.get("status") == "passed"
                and attempt.get("exit_code") == 0
                and valid_red is not None
                and index > valid_red
            ),
            None,
        )
        if valid_red is None:
            problems.append(f"{unit} has no validated failing red evidence")
        elif valid_green is None:
            problems.append(f"{unit} has no passing green evidence after red")
    return problems


def evaluate_case(case: str, repo: Path) -> EvaluationResult:
    """Judge raw evidence and git state from a completed fresh-agent run."""

    scenario = _scenario(case)
    repo = repo.resolve()
    problems: list[str] = []
    if not (repo / ".git").exists():
        return EvaluationResult(case, False, None, (f"not a git fixture repo: {repo}",))

    active_state_path = repo / ".codex" / "dev-loop" / "loop-state.json"
    if active_state_path.is_file():
        active_state = _load_json(active_state_path, problems)
        if active_state and active_state.get("phase") == "complete":
            problems.append("phase is complete but the run was not archived")
        else:
            problems.append("an active loop remains instead of an archived completed run")

    state_path = _latest_archive_state(repo)
    if state_path is None:
        problems.append("no archived loop-state.json exists")
        return EvaluationResult(case, False, None, tuple(problems))
    state = _load_json(state_path, problems)
    if state is None:
        return EvaluationResult(case, False, state_path, tuple(problems))

    if state.get("phase") != "complete":
        problems.append(f"archived phase is {state.get('phase')!r}, expected 'complete'")
    config = state.get("config")
    level = config.get("automation_level") if isinstance(config, dict) else None
    if level != scenario.automation_level:
        problems.append(
            f"automation boundary is {level!r}, expected {scenario.automation_level!r}"
        )
    blockers = state.get("blockers")
    if blockers not in (None, []):
        problems.append("completed evidence still contains blockers")
    final_report = state_path.parent / "final-report.md"
    if not final_report.is_file() or not final_report.read_text(encoding="utf-8").strip():
        problems.append("archived final-report.md is missing or empty")

    if case == "planning":
        problems.extend(
            _review_problems(
                state,
                {
                    "requirements-reviewer": {"pass"},
                    "plan-reviewer": {"pass"},
                },
            )
        )
        if state.get("test_attempts") not in (None, {}):
            problems.append("planning-only run recorded implementation test attempts")
        if state.get("quality_gate") not in (None, {}):
            problems.append("planning-only run crossed into the quality gate")
        git_state = state.get("git")
        if git_state not in (None, {}):
            problems.append("planning-only run crossed into Git delivery")
        if state.get("github_actions") not in (None, {}):
            problems.append("planning-only run recorded cloud checks")
    else:
        problems.extend(
            _review_problems(
                state,
                {
                    "requirements-reviewer": {"pass"},
                    "plan-reviewer": {"pass"},
                    "implementation-reviewer": {"pass"},
                    "docs-impact-reviewer": {"pass", "no-docs-needed"},
                },
            )
        )
        problems.extend(_tdd_problems(state))
        spec_merge = state.get("spec_merge")
        if not isinstance(spec_merge, dict) or spec_merge.get("status") != "merged":
            problems.append("commit case has no successful spec merge evidence")
        quality = state.get("quality_gate")
        if not isinstance(quality, dict) or quality.get("status") != "passed":
            problems.append("commit case has no passed quality gate")
        git_state = state.get("git")
        if not isinstance(git_state, dict):
            problems.append("commit case has no git evidence")
        else:
            commit = git_state.get("commit")
            branch = git_state.get("branch")
            head = _git(repo, "rev-parse", "HEAD", check=False).stdout.strip()
            current_branch = _git(repo, "branch", "--show-current", check=False).stdout.strip()
            if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
                problems.append("commit evidence is missing a full commit hash")
            elif commit.lower() != head.lower():
                problems.append("recorded commit is not the fixture repository HEAD")
            if branch != current_branch:
                problems.append("recorded branch does not match the fixture repository")
            if current_branch in {"main", "master", "develop"} or current_branch.startswith("release/"):
                problems.append(f"commit was created on protected branch {current_branch!r}")
            if any(git_state.get(key) for key in ("push", "pushed", "pr", "pr_url", "pr_number")):
                problems.append("commit-only evidence crossed into push or pull-request delivery")
        if state.get("github_actions") not in (None, {}):
            problems.append("commit-only run recorded cloud checks beyond its boundary")

    changed = _non_evidence_changes(repo)
    if changed:
        problems.append("uncommitted non-evidence changes remain: " + ", ".join(changed))
    return EvaluationResult(case, not problems, state_path, tuple(problems))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare neutral fresh-agent cases and evaluate their raw evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="create a disposable case and print its prompt")
    prepare.add_argument("--case", choices=sorted(SCENARIOS), required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--skill-dir", type=Path, default=ROOT)
    evaluate = subparsers.add_parser("evaluate", help="evaluate a completed case")
    evaluate.add_argument("--case", choices=sorted(SCENARIOS), required=True)
    evaluate.add_argument("--repo", type=Path, required=True)
    evaluate.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            prepared = prepare_case(args.case, args.out, args.skill_dir)
            print(prepared.prompt)
            print(f"FORWARD_TEST_REPO={prepared.repo}")
            print(f"FORWARD_TEST_HOME={prepared.home}")
            print(f"FORWARD_TEST_PROMPT={prepared.root / 'prompt.txt'}")
            return 0
        result = evaluate_case(args.case, args.repo)
    except (FileExistsError, FileNotFoundError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Forward test error: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(result.as_dict(), indent=2))
    elif result.passed:
        print(f"Forward test {result.case}: PASS")
        print(f"Evidence: {result.evidence_path}")
    else:
        print(f"Forward test {result.case}: FAIL")
        for problem in result.problems:
            print(f"- {problem}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
