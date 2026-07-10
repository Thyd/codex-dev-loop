from __future__ import annotations

from pathlib import Path
import re


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MAIN_SKILL = PACKAGE_ROOT / "SKILL.md"
REFERENCES = PACKAGE_ROOT / "references"


def test_trigger_time_skill_stays_compact() -> None:
    lines = MAIN_SKILL.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 220, f"SKILL.md has {len(lines)} lines"


def test_main_skill_routes_details_instead_of_embedding_phase_manuals() -> None:
    text = MAIN_SKILL.read_text(encoding="utf-8")
    for heading in (
        "## Intake And Clarification",
        "## Planning Artifacts",
        "## Development Loop",
        "## Git And PR Flow",
        "## Writeback And Archive",
    ):
        assert heading not in text
    for required in (
        "requirements-reviewer",
        "run-test --stage red",
        "record-spec-merge",
        "run-quality",
        "record-pr",
        "archive",
        "references/full-loop-workflow.md",
    ):
        assert required in text


def test_every_direct_markdown_reference_exists() -> None:
    text = MAIN_SKILL.read_text(encoding="utf-8")
    targets = re.findall(r"\[[^\]]+\]\(([^)]+\.md)\)", text)
    assert targets
    missing = [target for target in targets if not (PACKAGE_ROOT / target).is_file()]
    assert missing == []


def test_long_references_have_contents_navigation() -> None:
    missing = []
    for path in REFERENCES.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if len(text.splitlines()) > 100 and "## Contents" not in text:
            missing.append(path.name)
    assert missing == []


def test_openai_ui_prompt_still_matches_full_loop_trigger() -> None:
    text = (PACKAGE_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "$codex-dev-loop" in text
    assert "multi-module" in text
    assert "high-risk" in text

