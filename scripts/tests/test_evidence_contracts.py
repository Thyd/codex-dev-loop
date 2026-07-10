from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dev_loop_core.contracts import CORE_VERSION, EVIDENCE_SCHEMA_VERSION
from scripts.dev_loop_core.evidence import (
    EvidenceContractError,
    load_evidence_document,
    normalize_evidence_document,
    write_evidence_document,
)


def loop_state(**overrides: object) -> dict:
    state = {
        "phase": "intake",
        "reviews": {},
        "test_attempts": {},
        "quality_gate": {},
        "git": {},
        "github_actions": {},
        "blockers": [],
    }
    state.update(overrides)
    return state


def test_legacy_loop_state_is_upgraded_without_losing_unknown_fields() -> None:
    legacy = loop_state(
        phase="implementation",
        extension_field={"owned_by_host": True},
    )

    migrated, report = normalize_evidence_document(legacy, "loop-state")

    assert report.changed
    assert report.from_version == 0
    assert report.to_version == EVIDENCE_SCHEMA_VERSION
    assert migrated["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert migrated["kind"] == "loop-state"
    assert migrated["core_version"] == CORE_VERSION
    assert migrated["phase"] == "implementation"
    assert migrated["extension_field"] == {"owned_by_host": True}


def test_legacy_tdd_ledger_gets_typed_containers() -> None:
    migrated, report = normalize_evidence_document(
        {"attempts": {"behavior": []}},
        "tdd",
    )

    assert report.changed
    assert migrated["attempts"] == {"behavior": []}
    assert migrated["reviews"] == []
    assert migrated["kind"] == "tdd"


def test_future_schema_is_rejected_fail_closed() -> None:
    with pytest.raises(EvidenceContractError, match="newer than supported"):
        normalize_evidence_document(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION + 1,
                "kind": "loop-state",
            },
            "loop-state",
        )


def test_wrong_kind_is_rejected() -> None:
    with pytest.raises(EvidenceContractError, match="kind"):
        normalize_evidence_document(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "kind": "review",
                "reviews": [],
                "attempts": {},
            },
            "tdd",
        )


def test_invalid_container_shape_is_rejected() -> None:
    current = loop_state(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        kind="loop-state",
        core_version=CORE_VERSION,
        test_attempts=[],
    )
    with pytest.raises(EvidenceContractError, match="test_attempts"):
        normalize_evidence_document(current, "loop-state")


def test_atomic_write_round_trip_leaves_no_temporary_file(
    workspace_tmp_path: Path,
) -> None:
    target = workspace_tmp_path / "loop-state.json"

    write_evidence_document(target, loop_state(), "loop-state")
    loaded, report = load_evidence_document(target, "loop-state")

    assert not report.changed
    assert loaded["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert loaded["core_version"] == CORE_VERSION
    assert json.loads(target.read_text(encoding="utf-8")) == loaded
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []

