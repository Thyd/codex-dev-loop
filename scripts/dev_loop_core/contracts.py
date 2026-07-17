"""Stable version markers and evidence document identifiers."""

from __future__ import annotations


CORE_VERSION = "0.7.1"
EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_KINDS = frozenset({"loop-state", "tdd", "review"})


LOOP_STATE_CONTAINER_TYPES: dict[str, type] = {
    "reviews": dict,
    "test_attempts": dict,
    "quality_gate": dict,
    "git": dict,
    "github_actions": dict,
    "blockers": list,
}

LEDGER_CONTAINER_TYPES: dict[str, type] = {
    "attempts": dict,
    "reviews": list,
}
