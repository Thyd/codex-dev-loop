#!/usr/bin/env python3
"""Bundled fallback test gate for codex-dev-loop.

Speaks the same evidence protocol as automated-dev-executor's test_gate.py
(AUTODEV_TEST_META pointing at JSON with unit/status/command/cwd/exit_code/
log_path), so the harness can run the loop when the companion skill is not
installed — for example on Claude Code installs. The companion skill, when
present, still takes priority.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-") or "unit"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a test command as a fail-closed gate and save evidence.")
    parser.add_argument("--unit", default="unit", help="Development unit id.")
    parser.add_argument("--command", required=True, help="Test command to run.")
    parser.add_argument("--cwd", default=".", help="Working directory.")
    parser.add_argument("--log-dir", default=".codex/test-results", help="Log directory, relative to cwd unless absolute.")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds before the gate fails.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path(args.cwd).resolve()
    if not cwd.exists():
        print(f"Working directory does not exist: {cwd}", file=sys.stderr)
        return 2
    log_dir = Path(args.log_dir)
    if not log_dir.is_absolute():
        log_dir = cwd / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}-{slug(args.unit)}"
    log_path = log_dir / f"{base}.log"
    meta_path = log_dir / f"{base}.json"

    started = time.monotonic()
    metadata = {
        "unit": args.unit,
        "command": args.command,
        "cwd": str(cwd),
        "started_at": now_utc(),
        "timeout_seconds": args.timeout,
        "log_path": str(log_path),
        "gate": "codex-dev-loop-bundled",
    }

    try:
        completed = subprocess.run(
            args.command,
            cwd=str(cwd),
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.timeout,
        )
        output = completed.stdout or ""
        exit_code = completed.returncode
        status = "passed" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        output += f"\nTimed out after {args.timeout} seconds.\n"
        exit_code = 124
        status = "timeout"
    except Exception as exc:  # noqa: BLE001 - the gate must fail closed, not crash open
        output = f"Could not start test command: {exc}\n"
        exit_code = 127
        status = "error"

    metadata.update(
        {
            "finished_at": now_utc(),
            "duration_seconds": round(time.monotonic() - started, 3),
            "exit_code": exit_code,
            "status": status,
        }
    )
    log_path.write_text(output, encoding="utf-8", errors="replace")
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    print(f"AUTODEV_TEST_STATUS={status}")
    print(f"AUTODEV_TEST_LOG={log_path}")
    print(f"AUTODEV_TEST_META={meta_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
