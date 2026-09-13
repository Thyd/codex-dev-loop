from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.dev_loop_core.settings import normalize_config


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR = PACKAGE_ROOT / "scripts" / "configure_dev_loop.py"


def configure(output: Path, *arguments: str, answers: str = "") -> dict:
    completed = subprocess.run(
        [sys.executable, str(CONFIGURATOR), "--output", str(output), *arguments],
        input=answers, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize("choice,policy", [("1", "local_fallback"), ("2", "wait_for_payment")])
def test_first_run_persists_quota_choice(workspace_tmp_path: Path, choice: str, policy: str) -> None:
    config = configure(workspace_tmp_path / "config.json", answers=f"1\n1\n1\n1\n{choice}\n")
    assert config.get("ci_quota_policy") == policy
    assert normalize_config(config)["ci_quota_policy"] == policy


def test_config_upgrade_only_asks_missing_preference_and_preserves_settings(workspace_tmp_path: Path) -> None:
    output = workspace_tmp_path / "config.json"
    original = {"schema_version": 4, "automation_level": "commit_only", "source_types": ["markdown"],
                "quality_profile": "light", "test_failure_limit": 1, "max_units": 11,
                "custom_extension": {"enabled": True}}
    output.write_text(json.dumps(original), encoding="utf-8")
    config = configure(output, answers="1\n")
    assert config["ci_quota_policy"] == "local_fallback"
    for key, value in original.items():
        if key != "schema_version":
            assert config[key] == value
    assert configure(output, "--non-interactive") == config


def test_noninteractive_policy_override_preserves_other_preferences(workspace_tmp_path: Path) -> None:
    output = workspace_tmp_path / "config.json"
    first = configure(output, "--non-interactive", "--automation-level", "commit_only")
    assert first.get("ci_quota_policy") == "wait_for_payment"
    updated = configure(output, "--non-interactive", "--ci-quota-policy", "local_fallback")
    assert updated["automation_level"] == "commit_only"
    assert updated["ci_quota_policy"] == "local_fallback"


def test_legacy_config_waits_and_invalid_quota_policy_is_rejected() -> None:
    assert normalize_config({}).get("ci_quota_policy") == "wait_for_payment"
    with pytest.raises(SystemExit, match="ci_quota_policy"):
        normalize_config({"ci_quota_policy": "skip_checks"})


def test_policy_update_preserves_advanced_retry_limit(workspace_tmp_path: Path) -> None:
    output = workspace_tmp_path / "config.json"
    output.write_text(json.dumps({"max_test_retries_per_unit": 7, "test_failure_limit": 7}))
    updated = configure(output, "--non-interactive", "--ci-quota-policy", "local_fallback")
    assert updated["max_test_retries_per_unit"] == updated["test_failure_limit"] == 7


@pytest.mark.parametrize("policy", ["local_fallback", "wait_for_payment"])
def test_new_loops_reuse_saved_ci_quota_policy(workspace_tmp_path: Path, policy: str) -> None:
    config_path = workspace_tmp_path / "config.json"
    configure(config_path, "--non-interactive", "--ci-quota-policy", policy)
    for name in ("first-run", "next-run"):
        root = workspace_tmp_path / name
        completed = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "scripts" / "dev_loop_harness.py"),
             "--config", str(config_path), "--workspace", str(workspace_tmp_path),
             "--root", str(root), "init", "--draft"],
            text=True, capture_output=True, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        state = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        assert state["config"]["ci_quota_policy"] == policy


@pytest.mark.parametrize("interactive", [False, True])
def test_config_handles_legacy_windows_output_encoding(
    workspace_tmp_path: Path, interactive: bool,
) -> None:
    output = workspace_tmp_path / "codex-dev-loop.json"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"

    completed = subprocess.run(
        [
            sys.executable,
            str(CONFIGURATOR),
            *([] if interactive else ["--non-interactive"]),
            "--output",
            str(output),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        input=b"1\n1\n1\n1\n1\n" if interactive else None,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout.decode("ascii", errors="replace")
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["ci_quota_policy"] == (
        "local_fallback" if interactive else "wait_for_payment"
    )
