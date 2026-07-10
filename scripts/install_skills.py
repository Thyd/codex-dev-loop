#!/usr/bin/env python3
"""Install the composable dev-* sub-skills into the agent's skills directory.

The sub-skills live under this repo's skills/ as thin SKILL.md skins that call
the shared harness in codex-dev-loop/scripts/. This copies a selected subset
(or all) into <home>/skills/<name> so each becomes independently triggerable,
without turning them into independently versioned packages.

Home resolution: --home, else CODEX_DEV_LOOP_HOME, else ~/.codex.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


SKILLS_SOURCE = Path(__file__).resolve().parent.parent / "skills"


def resolve_home(explicit: str) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    override = os.environ.get("CODEX_DEV_LOOP_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex"


def available_skills() -> list[str]:
    if not SKILLS_SOURCE.exists():
        return []
    return sorted(p.name for p in SKILLS_SOURCE.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install codex-dev-loop composable sub-skills.")
    parser.add_argument("--home", default="", help="Agent home (default: CODEX_DEV_LOOP_HOME or ~/.codex).")
    parser.add_argument("--only", default="", help="Comma-separated subset of sub-skills to install (default: all).")
    parser.add_argument("--list", action="store_true", help="List available sub-skills and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be installed without copying.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skills = available_skills()
    if not skills:
        print(f"No sub-skills found under {SKILLS_SOURCE}.", file=sys.stderr)
        return 1

    if args.list:
        print("Available sub-skills:")
        for name in skills:
            print(f"- {name}")
        return 0

    selected = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else list(skills)
    unknown = [name for name in selected if name not in skills]
    if unknown:
        print(f"Unknown sub-skill(s): {', '.join(unknown)}. Available: {', '.join(skills)}", file=sys.stderr)
        return 1

    home = resolve_home(args.home)
    skills_dir = home / "skills"
    print(f"Target skills directory: {skills_dir}")
    for name in selected:
        src = SKILLS_SOURCE / name
        dest = skills_dir / name
        if args.dry_run:
            print(f"[dry-run] would install {name} -> {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        print(f"Installed {name} -> {dest}")

    if not args.dry_run:
        print(
            "\nDone. The sub-skills share the harness in codex-dev-loop/scripts/, "
            "so keep the main codex-dev-loop skill installed and updated. Re-run this installer after every core update "
            "to synchronize the copied SKILL.md files."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
