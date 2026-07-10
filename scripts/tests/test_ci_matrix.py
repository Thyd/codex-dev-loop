from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PACKAGE_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_covers_linux_windows_and_macos() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for runner in ("ubuntu-latest", "windows-latest", "macos-latest"):
        assert runner in text


def test_ci_covers_supported_python_anchors() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"3.11"' in text
    assert '"3.13"' in text


def test_ci_installs_locked_dev_dependencies_and_runs_pytest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pip install -r requirements-dev.txt" in text
    assert "python -m pytest" in text
    assert "python -m unittest" not in text
    assert "legacy_self_test.py --suite" not in text

