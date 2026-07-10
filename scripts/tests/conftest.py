from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import shutil
import uuid

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace_tmp_path() -> Iterator[Path]:
    """Create a child-process-safe temporary directory inside the repository."""

    root = PACKAGE_ROOT / ".tmp" / "pytest"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

