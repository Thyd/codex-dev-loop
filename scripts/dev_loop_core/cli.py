#!/usr/bin/env python3
"""Stable compatibility facade for the modular codex-dev-loop harness."""

from __future__ import annotations

import sys

from .settings import *  # noqa: F401,F403
from .workspace import *  # noqa: F401,F403
from .specs import *  # noqa: F401,F403
from .validation import *  # noqa: F401,F403
from .commands_loop import *  # noqa: F401,F403
from .commands_standalone import *  # noqa: F401,F403
from .parser import build_parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
