"""Composable standalone and installation integration coverage."""

from __future__ import annotations

import pytest

from .legacy_support import (
    ARTIFACTS,
    DEV_PLAN_TDD_RED,
    IMPLEMENTATION_REVIEW_BODY,
    Path,
    SCRIPTS_ROOT,
    SOURCE,
    configure_test_environment,
    fail_command,
    import_error_command,
    init_git_repo,
    json,
    must,
    must_record_spec_merge,
    pass_command,
    record_plan_review,
    record_requirements_review,
    run,
    subprocess,
    sys,
    test_workspace,
    write_artifacts,
    write_source,
)


def standalone(harness: Path, workspace: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return run([sys.executable, str(harness), "--workspace", str(workspace), *args], env=env)


def _run_standalone_integration_suite() -> int:
    """P1 composable standalone mode: guard-check, check-spec, standalone TDD,
    standalone review, the single-source-of-truth guard, and version handshake."""
    harness = (SCRIPTS_ROOT / "dev_loop_harness.py").resolve()

    with test_workspace(prefix="codex-dev-loop-standalone-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)

        # version handshake
        ok_version = standalone(harness, workspace, "version", "--require", "0.5.2")
        if ok_version.returncode != 0:
            print(ok_version.stdout)
            print("Expected the installed core to satisfy a 0.5.2 requirement.")
            return 1
        too_new = standalone(harness, workspace, "version", "--require", "99.0.0")
        if too_new.returncode == 0:
            print(too_new.stdout)
            print("Expected version --require to reject an impossible future version.")
            return 1

        # guard-check clean vs sensitive
        clean_guard = standalone(harness, workspace, "guard-check")
        if clean_guard.returncode != 0:
            print(clean_guard.stdout)
            print("Expected guard-check to pass on a non-sensitive change set.")
            return 1
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        dirty_guard = standalone(harness, workspace, "guard-check")
        if dirty_guard.returncode == 0:
            print(dirty_guard.stdout)
            print("Expected guard-check to flag a dependency manifest change.")
            return 1
        (workspace / "package.json").unlink()

        # check-spec fail then pass
        spec = workspace / "spec.md"
        spec.write_text("# Spec\n\n## Goal\n\n## Acceptance Criteria\n", encoding="utf-8")
        empty_spec = standalone(harness, workspace, "check-spec", "--file", str(spec))
        if empty_spec.returncode == 0:
            print(empty_spec.stdout)
            print("Expected check-spec to reject empty Goal/Acceptance Criteria.")
            return 1
        spec.write_text(SOURCE, encoding="utf-8")
        good_spec = standalone(harness, workspace, "check-spec", "--file", str(spec))
        if good_spec.returncode != 0:
            print(good_spec.stdout)
            print("Expected check-spec to accept a filled-in spec.")
            return 1
        spec.write_text("# 规格\n\n## 目标\n\n交付功能。\n\n## 验收标准\n\n- 行为可观察。\n", encoding="utf-8")
        chinese_spec = standalone(harness, workspace, "check-spec", "--file", str(spec))
        if chinese_spec.returncode != 0:
            print(chinese_spec.stdout)
            print("Expected check-spec to accept Chinese Goal/Acceptance headings.")
            return 1

        # scope-check command: reject undeclared files and sensitive paths
        spec.unlink()
        standalone_loop_root = workspace / ".codex" / "dev-loop"
        standalone_loop_root.mkdir(parents=True, exist_ok=True)
        (standalone_loop_root / "technical-design.md").write_text(ARTIFACTS["technical-design.md"], encoding="utf-8")
        (standalone_loop_root / "development-plan.md").write_text(ARTIFACTS["development-plan.md"], encoding="utf-8")
        (workspace / "unplanned.txt").write_text("scope drift\n", encoding="utf-8")
        scope_drift = standalone(
            harness,
            workspace,
            "scope-check",
            "--plan",
            str(workspace / ".codex" / "dev-loop" / "development-plan.md"),
            "--design",
            str(workspace / ".codex" / "dev-loop" / "technical-design.md"),
        )
        if scope_drift.returncode == 0:
            print(scope_drift.stdout)
            print("Expected scope-check to reject an undeclared changed file.")
            return 1
        (workspace / "unplanned.txt").unlink()
        (workspace / "app.txt").write_text("declared scope change\n", encoding="utf-8")
        scope_ok = standalone(
            harness,
            workspace,
            "scope-check",
            "--plan",
            str(workspace / ".codex" / "dev-loop" / "development-plan.md"),
            "--design",
            str(workspace / ".codex" / "dev-loop" / "technical-design.md"),
        )
        if scope_ok.returncode != 0:
            print(scope_ok.stdout)
            print("Expected scope-check to accept a change inside declared scope.")
            return 1
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        sensitive_scope = standalone(
            harness,
            workspace,
            "scope-check",
            "--plan",
            str(workspace / ".codex" / "dev-loop" / "development-plan.md"),
            "--design",
            str(workspace / ".codex" / "dev-loop" / "technical-design.md"),
        )
        if sensitive_scope.returncode == 0:
            print(sensitive_scope.stdout)
            print("Expected scope-check to reject undeclared dependency manifest changes.")
            return 1
        (workspace / "package.json").unlink()
        must(["git", "checkout", "--", "app.txt"], workspace)

        # validate-red command: reject infrastructure failures, accept intended assertion failures
        bad_red_log = workspace / "bad-red.log"
        bad_red_log.write_text("ModuleNotFoundError: No module named 'missing_dependency'\n", encoding="utf-8")
        invalid_red_log = standalone(harness, workspace, "validate-red", "--unit", "feat", "--log", str(bad_red_log), "--expected", "401 error message is missing")
        if invalid_red_log.returncode == 0:
            print(invalid_red_log.stdout)
            print("Expected validate-red to reject import/dependency failures.")
            return 1
        good_red_log = workspace / "good-red.log"
        good_red_log.write_text("AssertionError: 401 error message is missing\n", encoding="utf-8")
        valid_red_log = standalone(harness, workspace, "validate-red", "--unit", "feat", "--log", str(good_red_log), "--expected", "401 error message is missing")
        if valid_red_log.returncode != 0:
            print(valid_red_log.stdout)
            print("Expected validate-red to accept the declared assertion failure.")
            return 1

        # standalone TDD: green refused without red, then red -> green
        green_first = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "green", "--command", pass_command())
        if green_first.returncode == 0:
            print(green_first.stdout)
            print("Expected standalone green stage to be refused before red evidence exists.")
            return 1
        invalid_standalone_red = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "red", "--command", import_error_command())
        if invalid_standalone_red.returncode == 0:
            print(invalid_standalone_red.stdout)
            print("Expected standalone red import error to be rejected as the wrong failure reason.")
            return 1
        green_after_invalid = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "green", "--command", pass_command())
        if green_after_invalid.returncode == 0:
            print(green_after_invalid.stdout)
            print("Expected invalid standalone red evidence to not unlock green.")
            return 1
        missing_expected = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "red", "--command", fail_command())
        if missing_expected.returncode == 0:
            print(missing_expected.stdout)
            print("Expected red evidence without --expected-failure to be rejected.")
            return 1
        red = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "red", "--expected-failure", "intentional missing behavior", "--command", fail_command())
        if red.returncode != 0:
            print(red.stdout)
            print("Expected a failing standalone red run to record evidence.")
            return 1
        red_that_passes = standalone(harness, workspace, "standalone-test", "--label", "other", "--stage", "red", "--command", pass_command())
        if red_that_passes.returncode == 0:
            print(red_that_passes.stdout)
            print("Expected a passing red run to be flagged as not proving the behavior.")
            return 1
        green = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "green", "--command", pass_command())
        if green.returncode != 0:
            print(green.stdout)
            print("Expected standalone green stage to pass after red evidence exists.")
            return 1
        ledger = json.loads((workspace / ".codex" / "evidence" / "tdd" / "ledger.json").read_text(encoding="utf-8"))
        feat_attempts = ledger["attempts"]["feat"]
        accepted_stages = [
            item["stage"]
            for item in feat_attempts
            if item["stage"] != "red" or item.get("red_validation", {}).get("status") == "pass"
        ]
        if accepted_stages != ["red", "green"] or feat_attempts[0].get("red_validation", {}).get("status") != "invalid":
            print(json.dumps(ledger, indent=2))
            print("Expected the tdd ledger to keep invalid red attempts but only let validator-passed red unlock green.")
            return 1

        # standalone review bound to a target fingerprint
        (workspace / "target.txt").write_text("v1\n", encoding="utf-8")
        fp_out = standalone(harness, workspace, "standalone-fingerprint", "--target", "target.txt")
        fingerprint = ""
        for line in fp_out.stdout.splitlines():
            if line.strip().startswith("TARGET_FINGERPRINT="):
                fingerprint = line.strip().split("=", 1)[1]
        if not fingerprint:
            print(fp_out.stdout)
            print("Expected standalone-fingerprint to print TARGET_FINGERPRINT.")
            return 1
        report = tmp / "review.md"
        report.write_text(
            f"Agent ID: 019f-standalone-reviewer\nTarget Fingerprint: {fingerprint}\n\n" + IMPLEMENTATION_REVIEW_BODY,
            encoding="utf-8",
        )
        recorded = standalone(
            harness, workspace, "standalone-review",
            "--role", "implementation-reviewer", "--agent-id", "019f-standalone-reviewer",
            "--report", str(report), "--target", "target.txt",
        )
        if recorded.returncode != 0:
            print(recorded.stdout)
            print("Expected a passing standalone review with a current fingerprint to record.")
            return 1
        (workspace / "target.txt").write_text("v2 changed\n", encoding="utf-8")
        stale = standalone(
            harness, workspace, "standalone-review",
            "--role", "implementation-reviewer", "--agent-id", "019f-standalone-reviewer",
            "--report", str(report), "--target", "target.txt",
        )
        if stale.returncode == 0:
            print(stale.stdout)
            print("Expected a standalone review to go stale after the target changed.")
            return 1

        # single-source-of-truth guard: an active loop disables standalone
        loop_dir = workspace / ".codex" / "dev-loop"
        loop_dir.mkdir(parents=True, exist_ok=True)
        (loop_dir / "loop-state.json").write_text(json.dumps({"phase": "implementation"}), encoding="utf-8")
        blocked = standalone(harness, workspace, "standalone-test", "--label", "feat", "--stage", "red", "--command", fail_command())
        if blocked.returncode == 0:
            print(blocked.stdout)
            print("Expected standalone commands to be refused while a loop is active.")
            return 1
        guard_still_ok = standalone(harness, workspace, "guard-check")
        if guard_still_ok.returncode not in (0, 1):
            print(guard_still_ok.stdout)
            print("Expected guard-check to remain usable regardless of loop state.")
            return 1
        (loop_dir / "loop-state.json").write_text(json.dumps({"phase": "complete"}), encoding="utf-8")
        allowed = standalone(harness, workspace, "standalone-test", "--label", "feat2", "--stage", "red", "--expected-failure", "intentional missing behavior", "--command", fail_command())
        if allowed.returncode != 0:
            print(allowed.stdout)
            print("Expected standalone commands to resume once the loop is complete.")
            return 1

    if standalone_ship_and_spec_tests() != 0:
        return 1

    if standalone_upgrade_path_test() != 0:
        return 1

    if install_skills_test() != 0:
        return 1

    return 0


def install_skills_test() -> int:
    """install_skills.py discovers the dev-* skins and installs a subset into a
    relocated home."""
    installer = (SCRIPTS_ROOT / "install_skills.py").resolve()
    listing = run([sys.executable, str(installer), "--list"])
    if listing.returncode != 0:
        print(listing.stdout)
        print("Expected install_skills --list to succeed.")
        return 1
    for expected in ("dev-tdd", "dev-review", "dev-clarify", "dev-plan", "dev-spec", "dev-ship", "dev-debug"):
        if expected not in listing.stdout:
            print(listing.stdout)
            print(f"Expected install_skills to discover {expected}.")
            return 1
    with test_workspace(prefix="codex-dev-loop-install-") as raw_tmp:
        home = Path(raw_tmp) / "home"
        installed = run([sys.executable, str(installer), "--home", str(home), "--only", "dev-tdd,dev-ship"])
        if installed.returncode != 0:
            print(installed.stdout)
            print("Expected install_skills to install the requested subset.")
            return 1
        if not (home / "skills" / "dev-tdd" / "SKILL.md").exists() or not (home / "skills" / "dev-ship" / "SKILL.md").exists():
            print("Expected the selected sub-skills to be copied into <home>/skills.")
            return 1
        if (home / "skills" / "dev-plan").exists():
            print("Expected --only to install just the requested subset.")
            return 1
        unknown = run([sys.executable, str(installer), "--home", str(home), "--only", "does-not-exist"])
        if unknown.returncode == 0:
            print(unknown.stdout)
            print("Expected install_skills to reject an unknown sub-skill.")
            return 1
    return 0


def standalone_upgrade_path_test() -> int:
    """The escalation story: a user runs dev-tdd standalone, then upgrades to
    the full loop; adopt-evidence absorbs the fingerprint-current green so the
    unit gate is satisfied without re-running the test."""
    harness = (SCRIPTS_ROOT / "dev_loop_harness.py").resolve()

    with test_workspace(prefix="codex-dev-loop-upgrade-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)  # app.txt committed, on branch codex/test
        root = workspace / ".codex" / "dev-loop"

        def hp(*args: str) -> subprocess.CompletedProcess:
            return run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), *args])

        # 1) Standalone dev-tdd for a unit named dev-001 (no loop exists yet).
        red = standalone(harness, workspace, "standalone-test", "--label", "dev-001", "--stage", "red", "--expected-failure", "intentional missing behavior", "--command", fail_command())
        if red.returncode != 0:
            print(red.stdout)
            print("Expected standalone red to record before the loop exists.")
            return 1
        green = standalone(harness, workspace, "standalone-test", "--label", "dev-001", "--stage", "green", "--command", pass_command())
        if green.returncode != 0:
            print(green.stdout)
            print("Expected standalone green to record before the loop exists.")
            return 1

        # 2) Escalate: start the full loop in the same workspace.
        source = write_source(tmp)
        if hp("init", "--source", str(source)).returncode != 0:
            print("Expected loop init to succeed on the escalation path.")
            return 1
        record_requirements_review(harness, workspace, root, tmp)
        if hp("set-phase", "planning").returncode != 0:
            print("Expected intake -> planning to succeed.")
            return 1
        write_artifacts(root)
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED, encoding="utf-8")
        hp("set-phase", "plan_review")
        record_plan_review(harness, workspace, root, tmp)
        hp("set-phase", "branch")
        hp("record-branch", "--branch", "codex/test")
        hp("set-phase", "implementation")

        # 3) Adopt the standalone evidence; the unit gate should then be met
        #    without any loop run-test.
        adopt = hp("adopt-evidence")
        if adopt.returncode != 0 or "dev-001" not in adopt.stdout:
            print(adopt.stdout)
            print("Expected adopt-evidence to adopt the standalone green for dev-001.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        advanced = hp("set-phase", "implementation_review")
        if advanced.returncode != 0:
            print(advanced.stdout)
            print("Expected the adopted red+green evidence to satisfy the unit gate.")
            return 1

        # 4) A tree change after adoption must stale the adopted green.
        hp("set-phase", "implementation")
        (workspace / "app.txt").write_text("changed after adoption\n", encoding="utf-8")
        stale = hp("set-phase", "implementation_review")
        if stale.returncode == 0:
            print(stale.stdout)
            print("Expected a post-adoption tree change to stale the adopted evidence.")
            return 1

    return 0


def standalone_ship_and_spec_tests() -> int:
    """P2 composable commands: regression-only TDD mode, ship-check floor gate,
    and standalone check-spec-delta."""
    harness = (SCRIPTS_ROOT / "dev_loop_harness.py").resolve()

    with test_workspace(prefix="codex-dev-loop-ship-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)  # leaves HEAD on branch "codex/test"

        # ship-check with no green evidence is refused.
        no_evidence = standalone(harness, workspace, "ship-check", "--label", "ship")
        if no_evidence.returncode == 0:
            print(no_evidence.stdout)
            print("Expected ship-check to refuse without any green test evidence.")
            return 1

        # regression-only green needs no prior red.
        reg = standalone(harness, workspace, "standalone-test", "--label", "ship", "--mode", "regression-only", "--stage", "green", "--command", pass_command())
        if reg.returncode != 0:
            print(reg.stdout)
            print("Expected regression-only green to record without a red run.")
            return 1
        reg_red = standalone(harness, workspace, "standalone-test", "--label", "ship", "--mode", "regression-only", "--stage", "red", "--command", fail_command())
        if reg_red.returncode == 0:
            print(reg_red.stdout)
            print("Expected regression-only mode to reject a red stage.")
            return 1

        # ship-check now passes on the current tree.
        ok_ship = standalone(harness, workspace, "ship-check", "--label", "ship")
        if ok_ship.returncode != 0:
            print(ok_ship.stdout)
            print("Expected ship-check to pass with current green evidence on a feature branch.")
            return 1

        # changing the tree invalidates the green evidence.
        (workspace / "app.txt").write_text("shipped change\n", encoding="utf-8")
        stale_ship = standalone(harness, workspace, "ship-check", "--label", "ship")
        if stale_ship.returncode == 0:
            print(stale_ship.stdout)
            print("Expected ship-check to go stale after the working tree changed.")
            return 1
        docs_green = standalone(
            harness, workspace, "standalone-test", "--label", "docs", "--mode", "regression-only", "--stage", "green", "--command", pass_command()
        )
        if docs_green.returncode != 0:
            print(docs_green.stdout)
            print("Expected a second behavior label to record green on the current tree.")
            return 1
        incomplete_labels = standalone(harness, workspace, "ship-check", "--label", "ship", "--label", "docs")
        if incomplete_labels.returncode == 0:
            print(incomplete_labels.stdout)
            print("Expected ship-check to reject when any required behavior label is stale.")
            return 1
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        sensitive_tdd = standalone(
            harness, workspace, "standalone-test", "--label", "deps", "--mode", "regression-only", "--stage", "green", "--command", pass_command()
        )
        if sensitive_tdd.returncode == 0:
            print(sensitive_tdd.stdout)
            print("Expected standalone TDD to refuse sensitive-path changes.")
            return 1
        sensitive_ship = standalone(harness, workspace, "ship-check", "--label", "docs")
        if sensitive_ship.returncode == 0:
            print(sensitive_ship.stdout)
            print("Expected ship-check to refuse sensitive-path changes.")
            return 1

        # protected branch is refused.
        must(["git", "add", "-A"], workspace)
        must(["git", "commit", "-m", "wip"], workspace)
        must(["git", "checkout", "master"], workspace)
        protected = standalone(harness, workspace, "ship-check", "--label", "ship")
        if protected.returncode == 0:
            print(protected.stdout)
            print("Expected ship-check to refuse a protected branch.")
            return 1

    with test_workspace(prefix="codex-dev-loop-plan-only-") as raw_tmp:
        tmp = Path(raw_tmp)
        plan_root = tmp / "plan"
        plan_root.mkdir()
        for name in ["technical-design.md", "test-plan.md", "risk-analysis.md", "development-plan.md", "spec-delta.md"]:
            (plan_root / name).write_text(ARTIFACTS[name], encoding="utf-8")
        validator = (SCRIPTS_ROOT / "validate_dev_loop_artifacts.py").resolve()
        plan_only = run([sys.executable, str(validator), "--root", str(plan_root), "--profile", "plan-only"])
        if plan_only.returncode != 0:
            print(plan_only.stdout)
            print("Expected dev-plan's five artifacts to pass the plan-only validation profile.")
            return 1
        full_profile = run([sys.executable, str(validator), "--root", str(plan_root)])
        if full_profile.returncode == 0:
            print(full_profile.stdout)
            print("Expected the full artifact profile to still require source.md and decision-log.md.")
            return 1

    with test_workspace(prefix="codex-dev-loop-checkdelta-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        (workspace / "specs").mkdir()
        delta = workspace / "spec-delta.md"
        delta.write_text(
            "# Spec Delta\n\n## Capability: app-core\n\n### ADDED Requirements\n\n#### Requirement: Stores flag\n\nThe app records the flag.\n",
            encoding="utf-8",
        )
        missing_baseline = standalone(harness, workspace, "check-spec-delta", "--delta", str(delta), "--spec-dir", "specs")
        if missing_baseline.returncode == 0:
            print(missing_baseline.stdout)
            print("Expected check-spec-delta to fail while the baseline file is missing.")
            return 1
        (workspace / "specs" / "app-core.md").write_text(
            "# app-core Specification\n\n#### Requirement: Stores flag\n\nThe app records the flag.\n", encoding="utf-8"
        )
        matched = standalone(harness, workspace, "check-spec-delta", "--delta", str(delta), "--spec-dir", "specs")
        if matched.returncode != 0:
            print(matched.stdout)
            print("Expected check-spec-delta to pass once the baseline contains the requirement.")
            return 1
        (workspace / "specs" / "app-core.md").write_text(
            "# app-core Specification\n\n#### Requirement: Stores flag\n\nThe app stores a different value.\n",
            encoding="utf-8",
        )
        stale_body = standalone(harness, workspace, "check-spec-delta", "--delta", str(delta), "--spec-dir", "specs")
        if stale_body.returncode == 0:
            print(stale_body.stdout)
            print("Expected a matching title with stale requirement body to fail check-spec-delta.")
            return 1
        (workspace / "specs" / "app-core.md").write_text(
            "# app-core Specification\n\n#### Requirement: Stores flag\n\nThe app records the flag.\n\n"
            "#### Requirement: Stores flag\n\nDuplicate body.\n",
            encoding="utf-8",
        )
        duplicate = standalone(harness, workspace, "check-spec-delta", "--delta", str(delta), "--spec-dir", "specs")
        if duplicate.returncode == 0:
            print(duplicate.stdout)
            print("Expected duplicate baseline requirement titles to fail check-spec-delta.")
            return 1
        bad_capability = workspace / "bad-capability-delta.md"
        bad_capability.write_text(
            "# Spec Delta\n\n## Capability: app_core\n\n### ADDED Requirements\n\n"
            "#### Requirement: Stores flag\n\nThe app records the flag.\n",
            encoding="utf-8",
        )
        unsafe_name = standalone(harness, workspace, "check-spec-delta", "--delta", str(bad_capability), "--spec-dir", "specs")
        if unsafe_name.returncode == 0:
            print(unsafe_name.stdout)
            print("Expected a non-kebab-case capability name to fail check-spec-delta.")
            return 1
        no_impact = workspace / "delta2.md"
        no_impact.write_text("# Spec Delta\n\n## No Spec Impact\n\nDocs only.\n", encoding="utf-8")
        ni = standalone(harness, workspace, "check-spec-delta", "--delta", str(no_impact), "--spec-dir", "specs")
        if ni.returncode != 0:
            print(ni.stdout)
            print("Expected a No Spec Impact delta to pass check-spec-delta.")
            return 1

    return 0


@pytest.mark.integration
@pytest.mark.slow
def test_standalone_integration() -> None:
    configure_test_environment()
    assert _run_standalone_integration_suite() == 0
