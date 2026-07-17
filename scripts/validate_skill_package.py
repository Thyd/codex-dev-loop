#!/usr/bin/env python3
"""Validate discoverability and version consistency for every packaged skill."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAIN_SKILL = ROOT / "SKILL.md"
ADAPTER_SKILL = ROOT / "adapters" / "claude-code" / "SKILL.md"
VERSION_FILE = ROOT / "VERSION"
HARNESS = ROOT / "scripts" / "dev_loop_harness.py"
CORE_CONTRACTS = ROOT / "scripts" / "dev_loop_core" / "contracts.py"
CORE_CLI = ROOT / "scripts" / "dev_loop_core" / "cli.py"
CORE_MODULES = [
    ROOT / "scripts" / "dev_loop_core" / name
    for name in (
        "settings.py",
        "workspace.py",
        "specs.py",
        "validation.py",
        "commands_loop.py",
        "commands_standalone.py",
        "parser.py",
    )
]
SELF_TEST = ROOT / "scripts" / "self_test.py"
LEGACY_SELF_TEST = ROOT / "scripts" / "legacy_self_test.py"
FORWARD_TEST = ROOT / "scripts" / "forward_test.py"
PYTEST_CONFIG = ROOT / "pyproject.toml"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"


def skill_files() -> list[Path]:
    return [
        MAIN_SKILL,
        ADAPTER_SKILL,
        *sorted((ROOT / "skills").glob("*/SKILL.md")),
    ]


def frontmatter_problem(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return "starts with a UTF-8 BOM; frontmatter must begin at byte zero"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return f"is not valid UTF-8: {exc}"
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized_text.startswith("---\n"):
        return "does not begin with YAML frontmatter"
    parts = normalized_text.split("---\n", 2)
    if len(parts) < 3:
        return "has unterminated YAML frontmatter"
    fields = {
        line.split(":", 1)[0].strip()
        for line in parts[1].splitlines()
        if ":" in line and not line[:1].isspace()
    }
    missing = {"name", "description"} - fields
    extra = fields - {"name", "description"}
    if missing:
        return "is missing frontmatter field(s): " + ", ".join(sorted(missing))
    if extra:
        return "has unsupported frontmatter field(s): " + ", ".join(sorted(extra))
    return ""


def declared_version(path: Path) -> str:
    match = re.search(r"^Current version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else ""


def harness_version() -> str:
    match = re.search(r'^CORE_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', CORE_CONTRACTS.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else ""


def main() -> int:
    problems: list[str] = []
    for path in skill_files():
        problem = frontmatter_problem(path)
        if problem:
            problems.append(f"{path.relative_to(ROOT)} {problem}")

    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    markers = {
        "VERSION": version,
        "SKILL.md": declared_version(MAIN_SKILL),
        "adapters/claude-code/SKILL.md": declared_version(ADAPTER_SKILL),
        "scripts/dev_loop_core/contracts.py": harness_version(),
    }
    for name, marker in markers.items():
        if marker != version:
            problems.append(f"{name} declares {marker or '<missing>'}, expected {version}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"Version-v{version}-" not in readme:
        problems.append(f"README.md version badge does not declare {version}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first_release = re.search(r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\s+-", changelog, re.MULTILINE)
    if not first_release or first_release.group(1) != version:
        problems.append(f"CHANGELOG.md first release is {first_release.group(1) if first_release else '<missing>'}, expected {version}")
    handshake = f"version --require {version}"
    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        if handshake not in path.read_text(encoding="utf-8"):
            problems.append(f"{path.relative_to(ROOT)} is missing the core handshake: {handshake}")
    main_lines = len(MAIN_SKILL.read_text(encoding="utf-8").splitlines())
    if main_lines > 220:
        problems.append(f"SKILL.md has {main_lines} lines; keep the trigger-time body at or below 220 lines")
    main_text = MAIN_SKILL.read_text(encoding="utf-8")
    if "A run is not complete until `archive` succeeds" not in main_text:
        problems.append("SKILL.md must define successful archive as part of completion")
    for reference in sorted((ROOT / "references").glob("*.md")):
        reference_text = reference.read_text(encoding="utf-8")
        if len(reference_text.splitlines()) > 100 and "## Contents" not in reference_text:
            problems.append(f"references/{reference.name} is longer than 100 lines but has no Contents section")
    if not CORE_CLI.is_file():
        problems.append("scripts/dev_loop_core/cli.py is missing")
    elif len(CORE_CLI.read_text(encoding="utf-8").splitlines()) > 100:
        problems.append("scripts/dev_loop_core/cli.py must remain a compatibility facade (<= 100 lines)")
    for module in CORE_MODULES:
        if not module.is_file():
            problems.append(f"{module.relative_to(ROOT)} is missing")
            continue
        module_text = module.read_text(encoding="utf-8")
        module_lines = len(module_text.splitlines())
        if module_lines > 1200:
            problems.append(f"{module.relative_to(ROOT)} has {module_lines} lines; split modules above 1200 lines")
        if " import *" in module_text:
            problems.append(f"{module.relative_to(ROOT)} uses a wildcard import")
    if len(HARNESS.read_text(encoding="utf-8").splitlines()) > 60:
        problems.append("scripts/dev_loop_harness.py must remain a thin compatibility entrypoint (<= 60 lines)")
    if len(SELF_TEST.read_text(encoding="utf-8").splitlines()) > 100:
        problems.append("scripts/self_test.py must remain a thin focused-suite runner (<= 100 lines)")
    if not LEGACY_SELF_TEST.is_file():
        problems.append("scripts/legacy_self_test.py is missing")
    elif len(LEGACY_SELF_TEST.read_text(encoding="utf-8").splitlines()) > 100:
        problems.append("scripts/legacy_self_test.py must remain a thin pytest compatibility runner (<= 100 lines)")
    if not FORWARD_TEST.is_file():
        problems.append("scripts/forward_test.py is missing")
    elif len(FORWARD_TEST.read_text(encoding="utf-8").splitlines()) > 600:
        problems.append("scripts/forward_test.py exceeds its 600-line maintenance budget")
    if not PYTEST_CONFIG.is_file() or "[tool.pytest.ini_options]" not in PYTEST_CONFIG.read_text(encoding="utf-8"):
        problems.append("pyproject.toml is missing pytest configuration")
    if not DEV_REQUIREMENTS.is_file() or "pytest==" not in DEV_REQUIREMENTS.read_text(encoding="utf-8"):
        problems.append("requirements-dev.txt must pin pytest")
    for test_module in sorted((ROOT / "scripts" / "tests").glob("*.py")):
        test_lines = len(test_module.read_text(encoding="utf-8").splitlines())
        if test_lines > 1500:
            problems.append(f"{test_module.relative_to(ROOT)} has {test_lines} lines; split test modules above 1500 lines")

    if problems:
        print("Skill package validation failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print(f"Skill package is discoverable and version-aligned ({version}); checked {len(skill_files())} SKILL.md files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
