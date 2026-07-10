from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CORE = PACKAGE_ROOT / "scripts" / "dev_loop_core"
IMPLEMENTATION_MODULES = (
    "settings.py",
    "workspace.py",
    "specs.py",
    "validation.py",
    "commands_loop.py",
    "commands_standalone.py",
    "parser.py",
)


def test_cli_is_only_a_compatibility_facade() -> None:
    cli = CORE / "cli.py"
    assert len(cli.read_text(encoding="utf-8").splitlines()) <= 100


def test_harness_is_split_into_bounded_modules() -> None:
    missing = [name for name in IMPLEMENTATION_MODULES if not (CORE / name).is_file()]
    assert missing == []
    oversized = {
        name: len((CORE / name).read_text(encoding="utf-8").splitlines())
        for name in IMPLEMENTATION_MODULES
        if len((CORE / name).read_text(encoding="utf-8").splitlines()) > 1200
    }
    assert oversized == {}


def test_implementation_modules_do_not_use_wildcard_imports() -> None:
    offenders = []
    for name in IMPLEMENTATION_MODULES:
        text = (CORE / name).read_text(encoding="utf-8")
        if " import *" in text:
            offenders.append(name)
    assert offenders == []


def test_compatibility_facade_reexports_legacy_surface() -> None:
    text = (CORE / "cli.py").read_text(encoding="utf-8")
    for module in (
        "settings",
        "workspace",
        "specs",
        "validation",
        "commands_loop",
        "commands_standalone",
    ):
        assert f"from .{module} import *" in text
    assert "from .parser import build_parser" in text

