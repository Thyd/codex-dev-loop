from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
RUNNER = PACKAGE_ROOT / "scripts" / "self_test.py"
LEGACY_RUNNER = PACKAGE_ROOT / "scripts" / "legacy_self_test.py"
TESTS = PACKAGE_ROOT / "scripts" / "tests"
SUPPORT = TESTS / "legacy_support.py"
LOOP = TESTS / "test_loop_integration.py"
STANDALONE = TESTS / "test_standalone_integration.py"


def test_public_test_runners_are_thin_pytest_entrypoints() -> None:
    assert len(RUNNER.read_text(encoding="utf-8").splitlines()) <= 80
    assert len(LEGACY_RUNNER.read_text(encoding="utf-8").splitlines()) <= 100
    assert "pytest" in RUNNER.read_text(encoding="utf-8")
    assert "pytest" in LEGACY_RUNNER.read_text(encoding="utf-8")


def test_legacy_suite_is_physically_split_into_bounded_modules() -> None:
    missing = [path.name for path in (SUPPORT, LOOP, STANDALONE) if not path.is_file()]
    assert missing == []
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in (SUPPORT, LOOP, STANDALONE)
        if len(path.read_text(encoding="utf-8").splitlines()) > 1500
    }
    assert oversized == {}


def test_all_tests_use_pytest_not_unittest_testcase() -> None:
    offenders = []
    for path in TESTS.glob("test_*.py"):
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8")
        if "unittest.TestCase" in text or "import unittest" in text:
            offenders.append(path.name)
    assert offenders == []


def test_integration_suites_use_slow_and_integration_markers() -> None:
    for path in (LOOP, STANDALONE):
        text = path.read_text(encoding="utf-8")
        assert "@pytest.mark.integration" in text
        assert "@pytest.mark.slow" in text


def test_legacy_runner_advertises_compatibility_suites() -> None:
    completed = subprocess.run(
        [sys.executable, str(LEGACY_RUNNER), "--list-suites"],
        cwd=PACKAGE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == ["loop", "standalone"]
