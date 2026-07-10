"""Versioned JSON evidence contracts and atomic persistence.

The 0.5.x harness wrote structurally valid JSON without a document schema.
Version 0.6 treats those documents as schema version 0 and upgrades them in
memory. A mutating harness command persists the current schema on its next
write; the dedicated migration command can persist upgrades eagerly.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .contracts import (
    CORE_VERSION,
    EVIDENCE_KINDS,
    EVIDENCE_SCHEMA_VERSION,
    LEDGER_CONTAINER_TYPES,
    LOOP_STATE_CONTAINER_TYPES,
)


class EvidenceContractError(ValueError):
    """Raised when an evidence document cannot be trusted or migrated."""


@dataclass(frozen=True)
class MigrationReport:
    kind: str
    from_version: int
    to_version: int
    changed: bool
    changes: tuple[str, ...] = ()


def _schema_version(data: dict[str, Any]) -> int:
    value = data.get("schema_version", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceContractError("schema_version must be a non-negative integer")
    if value > EVIDENCE_SCHEMA_VERSION:
        raise EvidenceContractError(
            f"evidence schema {value} is newer than supported schema "
            f"{EVIDENCE_SCHEMA_VERSION}; update codex-dev-loop before continuing"
        )
    return value


def _container_types(kind: str) -> dict[str, type]:
    return LOOP_STATE_CONTAINER_TYPES if kind == "loop-state" else LEDGER_CONTAINER_TYPES


def _empty_container(expected_type: type) -> object:
    if expected_type is dict:
        return {}
    if expected_type is list:
        return []
    raise AssertionError(f"Unsupported evidence container type: {expected_type}")


def _validate_current_document(data: dict[str, Any], kind: str) -> None:
    if data.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceContractError(
            f"evidence document was not migrated to schema {EVIDENCE_SCHEMA_VERSION}"
        )
    if data.get("kind") != kind:
        raise EvidenceContractError(
            f"evidence kind mismatch: expected {kind!r}, found {data.get('kind')!r}"
        )
    core_version = data.get("core_version")
    if not isinstance(core_version, str) or not core_version.strip():
        raise EvidenceContractError("core_version must be a non-empty string")
    if kind == "loop-state":
        phase = data.get("phase")
        if not isinstance(phase, str) or not phase.strip():
            raise EvidenceContractError("loop-state phase must be a non-empty string")
    for field, expected_type in _container_types(kind).items():
        if not isinstance(data.get(field), expected_type):
            raise EvidenceContractError(
                f"{kind} field {field!r} must be {expected_type.__name__}"
            )


def normalize_evidence_document(
    raw: object,
    kind: str,
) -> tuple[dict[str, Any], MigrationReport]:
    """Validate and migrate a loop-state or standalone evidence document.

    Unknown fields are intentionally preserved so hosts may add namespaced
    metadata without a migration losing it.
    """

    if kind not in EVIDENCE_KINDS:
        raise EvidenceContractError(f"unknown evidence kind: {kind!r}")
    if not isinstance(raw, dict):
        raise EvidenceContractError("evidence document must be a JSON object")

    data: dict[str, Any] = copy.deepcopy(raw)
    from_version = _schema_version(data)
    changes: list[str] = []

    if from_version == 0:
        existing_kind = data.get("kind")
        if existing_kind not in {None, "", kind}:
            raise EvidenceContractError(
                f"legacy evidence kind mismatch: expected {kind!r}, found {existing_kind!r}"
            )
        data["schema_version"] = EVIDENCE_SCHEMA_VERSION
        data["kind"] = kind
        data["core_version"] = CORE_VERSION
        changes.extend(("schema_version", "kind", "core_version"))
        for field, expected_type in _container_types(kind).items():
            if field not in data:
                data[field] = _empty_container(expected_type)
                changes.append(field)

    _validate_current_document(data, kind)
    return data, MigrationReport(
        kind=kind,
        from_version=from_version,
        to_version=EVIDENCE_SCHEMA_VERSION,
        changed=bool(changes),
        changes=tuple(changes),
    )


def load_evidence_document(
    path: Path,
    kind: str,
) -> tuple[dict[str, Any], MigrationReport]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceContractError(f"evidence document does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceContractError(f"evidence document is not valid JSON: {path}: {exc}") from exc
    return normalize_evidence_document(raw, kind)


def write_evidence_document(path: Path, raw: object, kind: str) -> dict[str, Any]:
    """Write a current evidence document with same-directory atomic replace."""

    data, _report = normalize_evidence_document(raw, kind)
    data["schema_version"] = EVIDENCE_SCHEMA_VERSION
    data["kind"] = kind
    data["core_version"] = CORE_VERSION
    _validate_current_document(data, kind)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return data
