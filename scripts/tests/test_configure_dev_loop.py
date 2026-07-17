from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR = PACKAGE_ROOT / "scripts" / "configure_dev_loop.py"


def test_non_interactive_config_handles_legacy_windows_output_encoding(
    workspace_tmp_path: Path,
) -> None:
    output = workspace_tmp_path / "codex-dev-loop.json"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"

    completed = subprocess.run(
        [
            sys.executable,
            str(CONFIGURATOR),
            "--non-interactive",
            "--output",
            str(output),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout.decode("ascii", errors="replace")
    assert output.exists()
