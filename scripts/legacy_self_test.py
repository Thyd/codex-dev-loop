#!/usr/bin/env python3
"""Compatibility runner for the split pytest integration suites."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SUITES = {
    "loop": PACKAGE_ROOT / "scripts" / "tests" / "test_loop_integration.py",
    "standalone": PACKAGE_ROOT / "scripts" / "tests" / "test_standalone_integration.py",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["all", *SUITES], default="all")
    parser.add_argument("--list-suites", action="store_true")
    args = parser.parse_args()
    if args.list_suites:
        print("loop")
        print("standalone")
        return 0
    try:
        import pytest
    except ImportError as exc:
        raise SystemExit("pytest is required; install requirements-dev.txt") from exc
    os.chdir(PACKAGE_ROOT)
    sys.path.insert(0, str(PACKAGE_ROOT))
    targets = list(SUITES.values()) if args.suite == "all" else [SUITES[args.suite]]
    return int(pytest.main(["-q", *(str(path) for path in targets)]))


if __name__ == "__main__":
    raise SystemExit(main())
