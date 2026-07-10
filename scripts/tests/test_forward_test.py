from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.forward_test import evaluate_case, prepare_case


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def write_archived_state(repo: Path, state: dict[str, object]) -> Path:
    archive = repo / ".codex" / "dev-loop-archive" / "20260711T000000Z-run"
    archive.mkdir(parents=True)
    state_path = archive / "loop-state.json"
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (archive / "final-report.md").write_text("# Final Report\n\nComplete.\n", encoding="utf-8")
    return state_path


def common_state(level: str) -> dict[str, object]:
    return {
        "phase": "complete",
        "config": {"automation_level": level},
        "reviews": {},
        "test_attempts": {},
        "quality_gate": {},
        "git": {},
        "github_actions": {},
        "blockers": [],
    }


@pytest.mark.parametrize(
    ("case", "level", "module"),
    [
        ("planning", "planning_only", "catalog.py"),
        ("commit", "commit_only", "slugger.py"),
    ],
)
def test_prepare_case_creates_isolated_git_fixture_and_neutral_prompt(
    workspace_tmp_path: Path,
    case: str,
    level: str,
    module: str,
) -> None:
    prepared = prepare_case(case, workspace_tmp_path, PACKAGE_ROOT)

    config = json.loads((prepared.home / "config" / "codex-dev-loop.json").read_text(encoding="utf-8"))
    assert config["automation_level"] == level
    assert (prepared.repo / module).is_file()
    assert prepared.request.is_file()
    assert git(prepared.repo, "log", "-1", "--pretty=%s") == "forward-test fixture baseline"
    assert str((PACKAGE_ROOT / "SKILL.md").resolve()) in prepared.prompt
    assert str(prepared.repo.resolve()) in prepared.prompt
    assert str(prepared.home.resolve()) in prepared.prompt
    lowered = prepared.prompt.lower()
    assert "expected answer" not in lowered
    assert "suspected bug" not in lowered
    assert "test the skill" not in lowered


def test_planning_evaluation_accepts_reviewed_archived_boundary(workspace_tmp_path: Path) -> None:
    prepared = prepare_case("planning", workspace_tmp_path, PACKAGE_ROOT)
    state = common_state("planning_only")
    state["reviews"] = {
        "requirements-reviewer": {"decision": "pass", "agent_id": "fresh-requirements"},
        "plan-reviewer": {"decision": "pass", "agent_id": "fresh-plan"},
    }
    state_path = write_archived_state(prepared.repo, state)

    result = evaluate_case("planning", prepared.repo)

    assert result.passed, result.problems
    assert result.evidence_path == state_path


def test_commit_evaluation_requires_real_tdd_quality_commit_and_archive(workspace_tmp_path: Path) -> None:
    prepared = prepare_case("commit", workspace_tmp_path, PACKAGE_ROOT)
    git(prepared.repo, "checkout", "-b", "codex/forward-test")
    (prepared.repo / "specs").mkdir()
    (prepared.repo / "specs" / "slug-normalization.md").write_text(
        "# Slug normalization\n", encoding="utf-8"
    )
    (prepared.repo / "slugger.py").write_text(
        "def slugify(value: str) -> str:\n    return value.lower().strip()\n",
        encoding="utf-8",
    )
    git(prepared.repo, "add", "slugger.py", "specs/slug-normalization.md")
    git(prepared.repo, "commit", "-m", "feat: normalize slugs")
    commit = git(prepared.repo, "rev-parse", "HEAD")
    branch = git(prepared.repo, "branch", "--show-current")

    state = common_state("commit_only")
    state.update(
        {
            "reviews": {
                "requirements-reviewer": {"decision": "pass", "agent_id": "fresh-requirements"},
                "plan-reviewer": {"decision": "pass", "agent_id": "fresh-plan"},
                "implementation-reviewer": {"decision": "pass", "agent_id": "fresh-implementation"},
                "docs-impact-reviewer": {"decision": "no-docs-needed", "agent_id": "fresh-docs"},
            },
            "test_attempts": {
                "dev-001": [
                    {
                        "stage": "red",
                        "status": "failed",
                        "exit_code": 1,
                        "red_validation": {"status": "pass"},
                    },
                    {"stage": "green", "status": "passed", "exit_code": 0},
                ]
            },
            "spec_merge": {"status": "merged"},
            "quality_gate": {"status": "passed"},
            "git": {"branch": branch, "commit": commit},
        }
    )
    write_archived_state(prepared.repo, state)

    result = evaluate_case("commit", prepared.repo)

    assert result.passed, result.problems


def test_evaluation_rejects_complete_state_that_was_not_archived(workspace_tmp_path: Path) -> None:
    prepared = prepare_case("commit", workspace_tmp_path, PACKAGE_ROOT)
    active = prepared.repo / ".codex" / "dev-loop"
    active.mkdir(parents=True)
    (active / "loop-state.json").write_text(
        json.dumps(common_state("commit_only")) + "\n", encoding="utf-8"
    )

    result = evaluate_case("commit", prepared.repo)

    assert not result.passed
    assert any("not archived" in problem for problem in result.problems)


def test_main_skill_defines_archive_as_part_of_completion() -> None:
    text = (PACKAGE_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "A run is not complete until `archive` succeeds" in text
    assert "`.codex/dev-loop/` no longer exists" in text
