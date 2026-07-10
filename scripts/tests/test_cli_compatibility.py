from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from scripts import dev_loop_harness
from scripts.dev_loop_core.contracts import CORE_VERSION


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
HARNESS = PACKAGE_ROOT / "scripts" / "dev_loop_harness.py"
CORE_CLI = PACKAGE_ROOT / "scripts" / "dev_loop_core" / "cli.py"


def test_public_entrypoint_is_thin_and_core_cli_exists() -> None:
    assert CORE_CLI.is_file()
    assert len(HARNESS.read_text(encoding="utf-8").splitlines()) <= 60


def test_python_import_surface_remains_available() -> None:
    assert callable(dev_loop_harness.build_parser)
    assert callable(dev_loop_harness.cmd_init)
    assert callable(dev_loop_harness.cmd_standalone_test)
    assert dev_loop_harness.CORE_VERSION == CORE_VERSION


def test_all_legacy_subcommands_remain_registered() -> None:
    parser = dev_loop_harness.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    expected = {
        "init",
        "set-phase",
        "set-scale",
        "fingerprint",
        "record-branch",
        "record-commit",
        "record-review",
        "run-test",
        "record-test",
        "verify-units",
        "record-spec-merge",
        "archive",
        "run-quality",
        "record-pr",
        "record-cloud",
        "resolve-blocker",
        "validate",
        "doctor",
        "migrate-evidence",
        "version",
        "scope-check",
        "guard-check",
        "validate-red",
        "check-spec",
        "standalone-fingerprint",
        "standalone-test",
        "standalone-review",
        "check-spec-delta",
        "ship-check",
        "adopt-evidence",
    }
    assert expected.issubset(subparsers.choices)


def test_script_entrypoint_keeps_version_handshake() -> None:
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "version", "--require", "0.5.2"],
        cwd=PACKAGE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert f"codex-dev-loop-core {CORE_VERSION}" in completed.stdout

