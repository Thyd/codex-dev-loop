"""Living-spec delta parsing and baseline reconciliation."""

from __future__ import annotations
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from .contracts import CORE_VERSION, EVIDENCE_SCHEMA_VERSION
from .evidence import (
    EvidenceContractError,
    load_evidence_document,
    normalize_evidence_document,
    write_evidence_document,
)


def normalize_requirement_body(lines: list[str]) -> str:
    normalized = [line.rstrip() for line in lines]
    while normalized and not normalized[0].strip():
        normalized.pop(0)
    while normalized and not normalized[-1].strip():
        normalized.pop()
    compact: list[str] = []
    previous_blank = False
    for line in normalized:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = blank
    return "\n".join(compact)


def parse_spec_delta(text: str) -> dict:
    capabilities: dict[str, dict[str, list[dict[str, str]]]] = {}
    current_capability = ""
    current_bucket = ""
    no_impact_lines: list[str] = []
    in_no_impact = False
    bucket_names = {"added requirements": "added", "modified requirements": "modified", "removed requirements": "removed"}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("## capability:"):
            current_capability = line.split(":", 1)[1].strip()
            current_bucket = ""
            in_no_impact = False
            if current_capability and not current_capability.startswith("<"):
                capabilities.setdefault(current_capability, {"added": [], "modified": [], "removed": []})
            index += 1
            continue
        elif lower.startswith("## no spec impact"):
            in_no_impact = True
            current_capability = ""
            current_bucket = ""
            index += 1
            continue
        elif lower.startswith("## "):
            in_no_impact = False
            current_capability = ""
            current_bucket = ""
            index += 1
            continue
        elif lower.startswith("### "):
            bucket = bucket_names.get(lower[4:].strip(), "")
            current_bucket = bucket
            index += 1
            continue
        elif lower.startswith("#### requirement:"):
            title = line.split(":", 1)[1].strip()
            if current_capability and not current_capability.startswith("<") and current_bucket and title:
                end = index + 1
                while end < len(lines) and not re.match(r"^#{1,4}\s", lines[end].strip()):
                    end += 1
                capabilities[current_capability][current_bucket].append(
                    {"title": title, "body": normalize_requirement_body(lines[index + 1 : end])}
                )
                index = end
                continue
        elif in_no_impact and line and line not in {"-", "- ...", "TBD", "TODO", "N/A"}:
            no_impact_lines.append(line)
        index += 1
    declared = {
        name: buckets
        for name, buckets in capabilities.items()
        if any(buckets["added"]) or any(buckets["modified"]) or any(buckets["removed"])
    }
    return {"capabilities": declared, "no_impact_reason": " ".join(no_impact_lines).strip()}


def validate_delta_shape(delta: dict) -> dict:
    if delta["capabilities"] and delta["no_impact_reason"]:
        raise SystemExit("spec-delta.md is ambiguous: it declares capability requirements and a No Spec Impact reason. Keep exactly one.")
    if not delta["capabilities"] and not delta["no_impact_reason"]:
        raise SystemExit(
            "spec-delta.md must declare at least one '#### Requirement:' under a '## Capability:' section, "
            "or justify the change under '## No Spec Impact'."
        )
    for capability, buckets in delta["capabilities"].items():
        seen: dict[str, str] = {}
        for bucket, entries in buckets.items():
            for entry in entries:
                title = entry["title"].strip()
                key = title.casefold()
                if key in seen:
                    raise SystemExit(
                        f"spec-delta.md repeats requirement {title!r} in capability {capability!r} "
                        f"across {seen[key]} and {bucket}."
                    )
                seen[key] = bucket
                if bucket in {"added", "modified"} and not entry["body"]:
                    raise SystemExit(
                        f"spec-delta.md {bucket.upper()} requirement {title!r} in capability {capability!r} "
                        "must include the full requirement body."
                    )
    return delta


def load_spec_delta(root: Path) -> dict:
    path = root / "spec-delta.md"
    if not path.exists():
        raise SystemExit("Missing required planning artifact: spec-delta.md")
    return validate_delta_shape(parse_spec_delta(path.read_text(encoding="utf-8", errors="replace")))


def parse_baseline_requirements(text: str, filename: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    lines = text.splitlines()
    requirements: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line.lower().startswith("#### requirement:"):
            index += 1
            continue
        title = line.split(":", 1)[1].strip()
        key = title.casefold()
        end = index + 1
        while end < len(lines) and not re.match(r"^#{1,4}\s", lines[end].strip()):
            end += 1
        if key in requirements:
            problems.append(f"{filename} contains duplicate requirement title '#### Requirement: {title}'.")
        else:
            requirements[key] = {"title": title, "body": normalize_requirement_body(lines[index + 1 : end])}
        index = end
    return requirements, problems


def spec_delta_baseline_problems(delta: dict, spec_dir: Path) -> tuple[list[str], dict]:
    """Mechanically compare a parsed spec delta against the baseline files.

    Shared by the loop's record-spec-merge and the standalone check-spec-delta:
    every ADDED/MODIFIED requirement title must be present in
    <spec_dir>/<capability>.md, every REMOVED title must be gone.
    """
    problems: list[str] = []
    merged: dict[str, dict[str, list[str]]] = {}
    for capability, buckets in delta["capabilities"].items():
        assert_safe_capability_name(capability)
        spec_path = spec_dir / f"{capability}.md"
        if not spec_path.exists():
            problems.append(f"Missing spec baseline file for capability {capability!r}: {spec_path}")
            continue
        requirements, baseline_problems = parse_baseline_requirements(
            spec_path.read_text(encoding="utf-8", errors="replace"), spec_path.name
        )
        problems.extend(baseline_problems)
        for entry in [*buckets["added"], *buckets["modified"]]:
            title = entry["title"]
            baseline = requirements.get(title.casefold())
            if baseline is None:
                problems.append(f"{spec_path.name} is missing '#### Requirement: {title}' declared in the spec delta.")
            elif baseline["body"] != entry["body"]:
                problems.append(
                    f"{spec_path.name} requirement '#### Requirement: {title}' body differs from spec-delta.md."
                )
        for entry in buckets["removed"]:
            title = entry["title"]
            if title.casefold() in requirements:
                problems.append(f"{spec_path.name} still contains removed requirement '#### Requirement: {title}'.")
        merged[capability] = {
            bucket: [entry["title"] for entry in entries]
            for bucket, entries in buckets.items()
        }
    return problems, merged


def assert_safe_capability_name(name: str) -> None:
    if not name:
        raise SystemExit("spec-delta.md contains an empty capability name.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise SystemExit(
            f"Capability name {name!r} must be kebab-case (lowercase letters, digits, and single '-' separators) "
            "because it maps to a spec baseline filename."
        )
