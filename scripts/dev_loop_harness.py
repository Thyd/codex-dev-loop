#!/usr/bin/env python3
"""Backward-compatible entrypoint for the modular codex-dev-loop core.

Keep this path stable: installed sub-skills, adapters, and existing automation
invoke it directly. New implementation code belongs in ``dev_loop_core``.
"""

from __future__ import annotations

if __package__:
    from .dev_loop_core.cli import *  # noqa: F401,F403
    from .dev_loop_core.cli import main
else:
    from dev_loop_core.cli import *  # noqa: F401,F403
    from dev_loop_core.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

