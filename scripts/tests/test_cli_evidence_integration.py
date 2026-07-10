from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.dev_loop_core.contracts import CORE_VERSION, EVIDENCE_SCHEMA_VERSION


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
HARNESS = PACKAGE_ROOT / "scripts" / "dev_loop_harness.py"


@dataclass
class HarnessCase:
    scratch: Path

    @property
    def workspace(self) -> Path:
        return self.scratch / "workspace"

    @property
    def root(self) -> Path:
        return self.workspace / ".codex" / "dev-loop"

    @property
    def home(self) -> Path:
        return self.scratch / "home"

    @property
    def env(self) -> dict[str, str]:
        value = os.environ.copy()
        value["CODEX_DEV_LOOP_HOME"] = str(self.home)
        value["CODEX_DEV_LOOP_TEST_MODE"] = "1"
        return value

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(HARNESS),
                "--root",
                str(self.root),
                "--workspace",
                str(self.workspace),
                *arguments,
            ],
            cwd=self.workspace,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def init_loop(self) -> dict:
        completed = self.run("init", "--draft", "--scale", "small")
        assert completed.returncode == 0, completed.stderr
        return json.loads((self.root / "loop-state.json").read_text(encoding="utf-8"))


@pytest.fixture
def harness_case(workspace_tmp_path: Path) -> HarnessCase:
    case = HarnessCase(workspace_tmp_path)
    case.workspace.mkdir(parents=True)
    case.home.mkdir(parents=True)
    return case


@pytest.mark.integration
def test_init_writes_versioned_loop_state_and_json_introspection(
    harness_case: HarnessCase,
) -> None:
    state = harness_case.init_loop()
    assert state["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert state["kind"] == "loop-state"
    assert state["core_version"] == CORE_VERSION

    version = harness_case.run("version", "--json")
    assert version.returncode == 0, version.stderr
    version_payload = json.loads(version.stdout)
    assert version_payload["core_version"] == CORE_VERSION
    assert version_payload["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert "config_schema_version" in version_payload

    fingerprint = harness_case.run("fingerprint", "--json")
    assert fingerprint.returncode == 0, fingerprint.stderr
    assert set(json.loads(fingerprint.stdout)) == {
        "source_fingerprint",
        "plan_fingerprint",
        "workspace_fingerprint",
    }


@pytest.mark.integration
def test_doctor_previews_and_migrates_all_legacy_evidence(
    harness_case: HarnessCase,
) -> None:
    state = harness_case.init_loop()
    for field in ("schema_version", "kind", "core_version"):
        state.pop(field)
    (harness_case.root / "loop-state.json").write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )

    evidence_root = harness_case.workspace / ".codex" / "evidence"
    tdd = evidence_root / "tdd" / "ledger.json"
    review = evidence_root / "review" / "ledger.json"
    tdd.parent.mkdir(parents=True)
    review.parent.mkdir(parents=True)
    tdd.write_text(json.dumps({"attempts": {}}), encoding="utf-8")
    review.write_text(json.dumps({"reviews": []}), encoding="utf-8")

    doctor_before = harness_case.run("doctor", "--json")
    assert doctor_before.returncode == 1, doctor_before.stderr
    before_payload = json.loads(doctor_before.stdout)
    assert before_payload["status"] == "needs-migration"
    assert sum(item["needs_migration"] for item in before_payload["documents"]) == 3

    preview = harness_case.run("migrate-evidence", "--dry-run", "--json")
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["status"] == "needs-migration"
    assert all(not item["written"] for item in preview_payload["documents"])
    assert "schema_version" not in json.loads(tdd.read_text(encoding="utf-8"))

    migrate = harness_case.run("migrate-evidence", "--json")
    assert migrate.returncode == 0, migrate.stderr
    migrate_payload = json.loads(migrate.stdout)
    assert migrate_payload["status"] == "migrated"
    assert sum(item["written"] for item in migrate_payload["documents"]) == 3

    doctor_after = harness_case.run("doctor", "--json")
    assert doctor_after.returncode == 0, doctor_after.stderr
    assert json.loads(doctor_after.stdout)["status"] == "ok"
    migrated_state = json.loads(
        (harness_case.root / "loop-state.json").read_text(encoding="utf-8")
    )
    assert migrated_state["schema_version"] == EVIDENCE_SCHEMA_VERSION


@pytest.mark.integration
def test_future_or_corrupt_active_state_blocks_standalone_writes(
    harness_case: HarnessCase,
) -> None:
    harness_case.root.mkdir(parents=True)
    future = {
        "schema_version": EVIDENCE_SCHEMA_VERSION + 1,
        "kind": "loop-state",
        "core_version": "99.0.0",
        "phase": "implementation",
        "reviews": {},
        "test_attempts": {},
        "quality_gate": {},
        "git": {},
        "github_actions": {},
        "blockers": [],
    }
    (harness_case.root / "loop-state.json").write_text(
        json.dumps(future),
        encoding="utf-8",
    )

    doctor = harness_case.run("doctor", "--json")
    assert doctor.returncode != 0
    assert json.loads(doctor.stdout)["status"] == "error"

    standalone = harness_case.run(
        "standalone-test",
        "--label",
        "must-not-run",
        "--stage",
        "green",
        "--mode",
        "regression-only",
        "--command",
        f'"{sys.executable}" -c "raise SystemExit(0)"',
    )
    assert standalone.returncode != 0
    assert "newer than supported" in standalone.stderr + standalone.stdout

