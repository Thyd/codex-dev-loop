#!/usr/bin/env python3
"""Run the complete pytest suite for codex-dev-loop."""

from __future__ import annotations

import os
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        import pytest
    except ImportError as exc:
        raise SystemExit("pytest is required; install requirements-dev.txt") from exc
    os.chdir(PACKAGE_ROOT)
    sys.path.insert(0, str(PACKAGE_ROOT))
    return int(pytest.main(["-q", str(PACKAGE_ROOT / "scripts" / "tests")]))


if __name__ == "__main__":
    raise SystemExit(main())
