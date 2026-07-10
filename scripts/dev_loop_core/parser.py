"""Argument parser for the stable dev-loop command-line interface."""

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

from .settings import (
    SCALES,
    SOURCE_TYPES,
    TDD_MODES,
    TEST_STAGES,
)
from .workspace import (
    phase,
)
from .commands_loop import (
    cmd_archive,
    cmd_fingerprint,
    cmd_init,
    cmd_record_branch,
    cmd_record_cloud,
    cmd_record_commit,
    cmd_record_pr,
    cmd_record_review,
    cmd_record_spec_merge,
    cmd_record_test,
    cmd_resolve_blocker,
    cmd_run_quality,
    cmd_run_test,
    cmd_set_phase,
    cmd_set_scale,
    cmd_validate,
    cmd_verify_units,
)
from .commands_standalone import (
    cmd_adopt_evidence,
    cmd_check_spec,
    cmd_check_spec_delta,
    cmd_doctor,
    cmd_guard_check,
    cmd_migrate_evidence,
    cmd_scope_check,
    cmd_ship_check,
    cmd_standalone_fingerprint,
    cmd_standalone_review,
    cmd_standalone_test,
    cmd_validate_red,
    cmd_version,
)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex dev loop state helper.")
    parser.add_argument("--root", default=".codex/dev-loop")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--config", default=os.environ.get("CODEX_DEV_LOOP_CONFIG", ""), help="Path to codex-dev-loop config JSON.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("--source", default="")
    init.add_argument("--source-type", choices=sorted(SOURCE_TYPES), default="markdown")
    init.add_argument("--scale", choices=SCALES, default="", help="Task scale; defaults to default_scale from config.")
    init.add_argument("--draft", action="store_true", help="Start with a skeleton source.md and clarify Goal/Acceptance Criteria in the intake phase.")
    init.add_argument("--force", action="store_true", help="Overwrite the state of an existing (unarchived) loop.")
    init.set_defaults(func=cmd_init)

    phase = sub.add_parser("set-phase")
    phase.add_argument("phase")
    phase.set_defaults(func=cmd_set_phase)

    scale = sub.add_parser("set-scale")
    scale.add_argument("scale", choices=SCALES)
    scale.set_defaults(func=cmd_set_scale)

    fingerprint = sub.add_parser("fingerprint")
    fingerprint.add_argument("--json", action="store_true", help="Emit a stable JSON object instead of KEY=VALUE lines.")
    fingerprint.set_defaults(func=cmd_fingerprint)

    branch = sub.add_parser("record-branch")
    branch.add_argument("--branch", required=True)
    branch.set_defaults(func=cmd_record_branch)

    commit = sub.add_parser("record-commit")
    commit.add_argument("--commit", default="")
    commit.set_defaults(func=cmd_record_commit)

    review = sub.add_parser("record-review")
    review.add_argument("--role", required=True)
    review.add_argument("--report", required=True)
    review.add_argument("--agent-id", required=True)
    review.set_defaults(func=cmd_record_review)

    test = sub.add_parser("run-test")
    test.add_argument("--unit", required=True)
    test.add_argument("--command", required=True)
    test.add_argument("--stage", choices=sorted(TEST_STAGES), default="green", help="red records failing TDD evidence; green is the pass gate.")
    test.add_argument("--timeout", type=int, default=600)
    test.add_argument("--expected-failure", default="", help="For --stage red, text describing the intended missing behavior that should appear in the failure log.")
    test.add_argument("--test-gate-script", default="", help="Defaults to config override, companion skill, or bundled test_gate.py.")
    test.set_defaults(func=cmd_run_test)

    record_test = sub.add_parser("record-test")
    record_test.add_argument("--unit", required=True)
    record_test.add_argument("--meta", required=True, help="AUTODEV_TEST_META JSON produced by the test gate inside the worktree.")
    record_test.add_argument("--worktree", required=True, help="Linked git worktree where the unit-implementer ran the gate.")
    record_test.add_argument("--stage", choices=sorted(TEST_STAGES), default="green")
    record_test.add_argument("--expected-failure", default="", help="For --stage red, text describing the intended missing behavior that should appear in the failure log.")
    record_test.set_defaults(func=cmd_record_test)

    verify = sub.add_parser("verify-units")
    verify.add_argument("--timeout", type=int, default=600)
    verify.set_defaults(func=cmd_verify_units)

    spec_merge = sub.add_parser("record-spec-merge")
    spec_merge.set_defaults(func=cmd_record_spec_merge)

    archive = sub.add_parser("archive")
    archive.set_defaults(func=cmd_archive)

    quality = sub.add_parser("run-quality")
    quality.add_argument("--out-dir", default="")
    quality.add_argument("--alignment-report", default=".codex/quality-gate/subagent-alignment.md")
    quality.add_argument("--timeout", type=int, default=900)
    quality.add_argument("--require", default="", help="Additional required gates; configured profile gates are always required.")
    quality.add_argument("--pr-url", default="")
    quality.add_argument("--command", action="append", default=[], metavar="GATE=COMMAND")
    quality.set_defaults(func=cmd_run_quality)

    pr = sub.add_parser("record-pr")
    pr.add_argument("--branch", required=True)
    pr.add_argument("--commit", required=True)
    pr.add_argument("--pr-url", required=True)
    pr.add_argument("--gh", default="gh")
    pr.add_argument("--evidence", default="")
    pr.add_argument("--allow-local-simulation", action="store_true")
    pr.set_defaults(func=cmd_record_pr)

    cloud = sub.add_parser("record-cloud")
    cloud.add_argument("--status", required=True, choices=["passed", "failed", "blocked"])
    cloud.add_argument("--gh", default="gh")
    cloud.add_argument("--evidence", default="")
    cloud.add_argument("--extra-required-check", action="append", default=[])
    cloud.add_argument("--allow-local-simulation", action="store_true")
    cloud.set_defaults(func=cmd_record_cloud)

    resolve = sub.add_parser("resolve-blocker")
    resolve.add_argument("--reason", required=True, help="How the blocker was addressed; recorded in blocker-resolutions.md.")
    resolve.set_defaults(func=cmd_resolve_blocker)

    validate = sub.add_parser("validate")
    validate.add_argument("--require-reviews", action="store_true")
    validate.add_argument("--require-final", action="store_true")
    validate.set_defaults(func=cmd_validate)

    doctor = sub.add_parser("doctor", help="Inspect config and evidence schema compatibility without writing.")
    doctor.add_argument("--json", action="store_true", help="Emit a stable machine-readable report.")
    doctor.set_defaults(func=cmd_doctor)

    migrate = sub.add_parser("migrate-evidence", help="Upgrade legacy loop and standalone evidence to the current schema.")
    migrate.add_argument("--dry-run", action="store_true", help="Report migrations without writing files.")
    migrate.add_argument("--json", action="store_true", help="Emit a stable machine-readable report.")
    migrate.set_defaults(func=cmd_migrate_evidence)

    # Composable standalone commands (used by the dev-* sub-skills).
    version = sub.add_parser("version")
    version.add_argument("--require", default="", help="Exit non-zero if the installed core is older than this version.")
    version.add_argument("--json", action="store_true", help="Emit core, evidence, and config versions as JSON.")
    version.set_defaults(func=cmd_version)

    scope = sub.add_parser("scope-check")
    scope.add_argument("--plan", default="", help="development-plan.md path; defaults to <root>/development-plan.md.")
    scope.add_argument("--design", default="", help="technical-design.md path; defaults to <root>/technical-design.md.")
    scope.add_argument("--base-ref", default="", help="Optional git ref to include committed branch diff in the check.")
    scope.set_defaults(func=cmd_scope_check)

    guard = sub.add_parser("guard-check")
    guard.set_defaults(func=cmd_guard_check)

    validate_red = sub.add_parser("validate-red")
    validate_red.add_argument("--unit", required=True)
    validate_red.add_argument("--log", required=True, help="Red-stage test log to inspect.")
    validate_red.add_argument("--expected", default="", help="Expected missing behavior or assertion text for the red failure.")
    validate_red.add_argument("--status", choices=["passed", "failed", "timeout", "error"], default="failed")
    validate_red.set_defaults(func=cmd_validate_red)

    check_spec = sub.add_parser("check-spec")
    check_spec.add_argument("--file", required=True, help="Spec/source file to validate for a non-empty Goal and Acceptance Criteria.")
    check_spec.set_defaults(func=cmd_check_spec)

    standalone_fp = sub.add_parser("standalone-fingerprint")
    standalone_fp.add_argument("--target", required=True, help="Comma-separated workspace-relative files to fingerprint.")
    standalone_fp.set_defaults(func=cmd_standalone_fingerprint)

    standalone_test = sub.add_parser("standalone-test")
    standalone_test.add_argument("--label", required=True, help="Identifier for the behavior under test.")
    standalone_test.add_argument("--command", required=True)
    standalone_test.add_argument("--stage", choices=sorted(TEST_STAGES), default="green")
    standalone_test.add_argument("--mode", choices=sorted(TDD_MODES), default="red", help="red enforces red-before-green; regression-only records green for changes covered by existing tests.")
    standalone_test.add_argument("--expected-failure", default="", help="For --stage red, text describing the intended missing behavior that should appear in the failure log.")
    standalone_test.add_argument("--timeout", type=int, default=600)
    standalone_test.add_argument("--test-gate-script", default="")
    standalone_test.set_defaults(func=cmd_standalone_test)

    standalone_review = sub.add_parser("standalone-review")
    standalone_review.add_argument("--role", required=True, help="One of plan-reviewer, implementation-reviewer, risk-reviewer.")
    standalone_review.add_argument("--report", required=True)
    standalone_review.add_argument("--agent-id", required=True)
    standalone_review.add_argument("--target", required=True, help="Comma-separated workspace-relative files under review.")
    standalone_review.set_defaults(func=cmd_standalone_review)

    check_delta = sub.add_parser("check-spec-delta")
    check_delta.add_argument("--delta", required=True, help="Spec delta file to validate against the baseline.")
    check_delta.add_argument("--spec-dir", default="specs", help="Baseline spec directory, relative to the workspace.")
    check_delta.set_defaults(func=cmd_check_spec_delta)

    ship = sub.add_parser("ship-check")
    ship.add_argument("--label", action="append", required=True, help="Required standalone behavior label; repeat for every behavior in the change.")
    ship.set_defaults(func=cmd_ship_check)

    adopt = sub.add_parser("adopt-evidence")
    adopt.set_defaults(func=cmd_adopt_evidence)
    return parser
