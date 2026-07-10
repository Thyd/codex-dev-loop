"""End-to-end full-loop integration coverage."""

from __future__ import annotations

import pytest

from .legacy_support import (
    ARTIFACTS,
    DEV_PLAN_TDD_RED,
    DOCS_NEEDED_REVIEW_BODY,
    IMPLEMENTATION_REVIEW_BODY,
    MERGE_INTEGRATOR_REVIEW_BODY,
    PLAN_REVIEW_BODY,
    Path,
    RISK_REVIEW_BODY,
    SCRIPTS_ROOT,
    SOURCE,
    SPEC_BASELINE_APP_CORE,
    SPEC_DELTA_CAPABILITY,
    SPEC_DELTA_REMOVED,
    append_dev_002,
    configure_test_environment,
    fail_command,
    import_error_command,
    init_git_repo,
    init_loop,
    json,
    must,
    must_record_spec_merge,
    os,
    pass_command,
    record_docs_impact,
    record_plan_review,
    record_requirements_review,
    record_review,
    record_spec_merge,
    run,
    run_bundled_test_gate,
    run_failing_quality,
    run_quality,
    run_test,
    sys,
    test_workspace,
    write_artifacts,
    write_fake_codex_home,
    write_prefilled_quality_dir,
    write_review,
    write_source,
)


def _run_loop_integration_suite() -> int:
    configurator = (SCRIPTS_ROOT / "configure_dev_loop.py").resolve()
    validator = (SCRIPTS_ROOT / "validate_dev_loop_artifacts.py").resolve()
    harness = (SCRIPTS_ROOT / "dev_loop_harness.py").resolve()
    with test_workspace(prefix="codex-dev-loop-config-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "codex-dev-loop.json"
        configured = run([sys.executable, str(configurator), "--non-interactive", "--output", str(config_path)])
        if configured.returncode != 0:
            print(configured.stdout)
            print("Expected configure_dev_loop.py to write default config.")
            return 1
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if data.get("automation_level") != "pr_without_merge" or data.get("quality_profile") != "standard" or data.get("test_failure_limit") != 3:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("Expected default first-run config values.")
            return 1
        if "risk_mode" in data:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("Expected schema v4 to remove the non-functional risk_mode preference.")
            return 1
        expected_budget = {
            "max_units": 8,
            "max_files_changed": 20,
            "max_test_retries_per_unit": 3,
            "max_review_iterations": 3,
            "max_quality_fix_rounds": 2,
            "max_diff_lines": 1200,
        }
        if data.get("schema_version") != 4 or data.get("default_scale") != "standard" or data.get("spec_dir") != "specs":
            print(json.dumps(data, indent=2, ensure_ascii=False))
            print("Expected schema v4 defaults from the configuration wizard.")
            return 1
        for key, value in expected_budget.items():
            if data.get(key) != value:
                print(json.dumps(data, indent=2, ensure_ascii=False))
                print(f"Expected budget default {key}={value} from the configuration wizard.")
                return 1

    with test_workspace(prefix="codex-dev-loop-self-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        root = tmp / ".codex" / "dev-loop"
        root.mkdir(parents=True)
        (root / "source.md").write_text(SOURCE, encoding="utf-8")
        write_artifacts(root)

        ok = run([sys.executable, str(validator), "--root", str(root)])
        if ok.returncode != 0:
            print(ok.stdout)
            print("Expected complete artifacts to pass.")
            return 1

        (root / "test-plan.md").unlink()
        missing = run([sys.executable, str(validator), "--root", str(root)])
        if missing.returncode == 0:
            print(missing.stdout)
            print("Expected missing test-plan.md to fail.")
            return 1

    with test_workspace(prefix="codex-dev-loop-harness-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)

        no_source = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(tmp / "bad-root"), "init"])
        if no_source.returncode == 0:
            print(no_source.stdout)
            print("Expected init without source to fail.")
            return 1

        jump = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if jump.returncode == 0:
            print(jump.stdout)
            print("Expected direct jump to complete to fail.")
            return 1

        to_plan_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if to_plan_review.returncode != 0:
            print(to_plan_review.stdout)
            print("Expected transition to plan_review to pass.")
            return 1

        synthetic = tmp / "bad-review.md"
        synthetic.write_text("Decision: pass\n", encoding="utf-8")
        bad_review = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-review",
                "--role",
                "plan-reviewer",
                "--agent-id",
                "019f-plan-reviewer",
                "--report",
                str(synthetic),
            ]
        )
        if bad_review.returncode == 0:
            print(bad_review.stdout)
            print("Expected review without provenance and required sections to fail.")
            return 1

        record_plan_review(harness, workspace, root, tmp)
        (root / "technical-design.md").write_text(ARTIFACTS["technical-design.md"] + "\nExtra change.\n", encoding="utf-8")
        stale_plan = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        if stale_plan.returncode == 0:
            print(stale_plan.stdout)
            print("Expected changed planning artifact to stale the plan review.")
            return 1

    with test_workspace(prefix="codex-dev-loop-planning-only-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "planning-only.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "planning_only",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        complete_planning_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if complete_planning_only.returncode != 0:
            print(complete_planning_only.stdout)
            print("Expected planning_only automation config to allow completion after plan review.")
            return 1
        validate_planning_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "validate", "--require-reviews", "--require-final"])
        if validate_planning_only.returncode != 0:
            print(validate_planning_only.stdout)
            print("Expected planning_only final validation to require only planning records.")
            return 1
        wrapper_validate_planning_only = run([sys.executable, str(validator), "--workspace", str(workspace), "--root", str(root), "--require-final"])
        if wrapper_validate_planning_only.returncode != 0:
            print(wrapper_validate_planning_only.stdout)
            print("Expected legacy validator to reuse planning_only harness final validation.")
            return 1
        blocked_by_config = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        if blocked_by_config.returncode == 0:
            print(blocked_by_config.stdout)
            print("Expected planning_only automation config to block branch phase.")
            return 1
        archived = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "archive"])
        if archived.returncode != 0:
            print(archived.stdout)
            print("Expected archive to move the completed loop records.")
            return 1
        if (root / "loop-state.json").exists():
            print("Expected archive to move loop-state.json out of the working root.")
            return 1
        archive_base = root.parent / f"{root.name}-archive"
        archived_runs = list(archive_base.glob("*/loop-state.json"))
        if len(archived_runs) != 1:
            print(f"Expected exactly one archived run under {archive_base}.")
            return 1
        source = write_source(tmp)
        fresh_init = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "--config", str(config_path), "init", "--source", str(source)]
        )
        if fresh_init.returncode != 0:
            print(fresh_init.stdout)
            print("Expected init to start cleanly after archive without --force.")
            return 1

    with test_workspace(prefix="codex-dev-loop-source-type-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        source = write_source(tmp)
        config_path = tmp / "markdown-only.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown"],
                    "quality_profile": "standard",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        blocked_source = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(workspace / ".codex" / "dev-loop"),
                "--config",
                str(config_path),
                "init",
                "--source",
                str(source),
                "--source-type",
                "notion",
            ]
        )
        if blocked_source.returncode == 0:
            print(blocked_source.stdout)
            print("Expected source_types config to block disallowed Notion source intake.")
            return 1

    with test_workspace(prefix="codex-dev-loop-failures-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        failed = None
        for _ in range(3):
            failed = run_test(harness, workspace, root, "dev-001", fail_command())
        if failed is None or failed.returncode != 0:
            print(failed.stdout if failed else "")
            print("Expected three failures to stay within the default retry limit of 3.")
            return 1
        failed = run_test(harness, workspace, root, "dev-001", fail_command())
        if failed.returncode == 0:
            print(failed.stdout)
            print("Expected the fourth consecutive failure to exceed the retry limit and block.")
            return 1
        blocked_test = run_test(harness, workspace, root, "dev-001", fail_command())
        if blocked_test.returncode == 0:
            print(blocked_test.stdout)
            print("Expected run-test to be rejected while the loop is blocked.")
            return 1
        no_reason = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "resolve-blocker", "--reason", "short"])
        if no_reason.returncode == 0:
            print(no_reason.stdout)
            print("Expected resolve-blocker to reject a trivial reason.")
            return 1
        resolved = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "resolve-blocker",
                "--reason",
                "Fixed the failing dependency pin so the unit test can run again.",
            ]
        )
        if resolved.returncode != 0:
            print(resolved.stdout)
            print("Expected resolve-blocker to clear the blocker with a written reason.")
            return 1
        if not (root / "blocker-resolutions.md").exists():
            print("Expected resolve-blocker to append to blocker-resolutions.md.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if state_data.get("blockers"):
            print("Expected blockers to be empty after resolve-blocker.")
            return 1
        if not state_data.get("blocker_resolutions"):
            print("Expected blocker_resolutions to be recorded in state.")
            return 1
        after_resolve = run_test(harness, workspace, root, "dev-001", fail_command())
        if after_resolve.returncode != 0:
            print(after_resolve.stdout)
            print("Expected the failure counter to reset after resolve-blocker.")
            return 1

    with test_workspace(prefix="codex-dev-loop-intake-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        root = workspace / ".codex" / "dev-loop"
        base = [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root)]
        drafted = run([*base, "init", "--draft"])
        if drafted.returncode != 0:
            print(drafted.stdout)
            print("Expected init --draft to start a clarification-first loop.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if state_data.get("phase") != "intake":
            print("Expected init to start in the intake phase.")
            return 1
        if not (root / "clarification-log.md").exists():
            print("Expected init to create clarification-log.md.")
            return 1
        unclear = run([*base, "set-phase", "planning"])
        if unclear.returncode == 0:
            print(unclear.stdout)
            print("Expected planning to be blocked while Goal and Acceptance Criteria are empty.")
            return 1
        (root / "source.md").write_text(SOURCE, encoding="utf-8")
        clarified = run([*base, "set-phase", "planning"])
        if clarified.returncode == 0:
            print(clarified.stdout)
            print("Expected planning to stay blocked until requirements-reviewer passes.")
            return 1
        record_requirements_review(harness, workspace, root, tmp)
        (root / "clarification-log.md").write_text(
            (root / "clarification-log.md").read_text(encoding="utf-8") + "\n## Approved Update\n\n- User changed a load-bearing assumption.\n",
            encoding="utf-8",
        )
        stale_clarification = run([*base, "set-phase", "planning"])
        if stale_clarification.returncode == 0:
            print(stale_clarification.stdout)
            print("Expected a clarification-log change to stale the requirements review.")
            return 1
        record_requirements_review(harness, workspace, root, tmp)
        clarified = run([*base, "set-phase", "planning"])
        if clarified.returncode != 0:
            print(clarified.stdout)
            print("Expected planning to open once requirements-reviewer passes for the clarified source.")
            return 1
        reinit = run([*base, "init", "--draft"])
        if reinit.returncode == 0:
            print(reinit.stdout)
            print("Expected init to refuse overwriting an unarchived loop without --force.")
            return 1
        back_to_intake = run([*base, "set-phase", "intake"])
        if back_to_intake.returncode != 0:
            print(back_to_intake.stdout)
            print("Expected planning -> intake backtrack for re-clarification.")
            return 1
        forced = run([*base, "init", "--draft", "--force"])
        if forced.returncode != 0:
            print(forced.stdout)
            print("Expected init --force to restart the loop state.")
            return 1

    with test_workspace(prefix="codex-dev-loop-tdd-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED.replace("- TDD: red", "- TDD: bogus"), encoding="utf-8")
        invalid_mode = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if invalid_mode.returncode == 0:
            print(invalid_mode.stdout)
            print("Expected invalid '- TDD:' value to fail artifact validation.")
            return 1
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED, encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        green_without_red = run_test(harness, workspace, root, "dev-001", pass_command())
        if green_without_red.returncode == 0:
            print(green_without_red.stdout)
            print("Expected the green stage to be rejected before red-stage TDD evidence exists.")
            return 1
        red_that_passes = run_test(harness, workspace, root, "dev-001", pass_command(), stage="red")
        if red_that_passes.returncode == 0:
            print(red_that_passes.stdout)
            print("Expected a red-stage run that passes to be flagged as not proving the behavior.")
            return 1
        still_no_green = run_test(harness, workspace, root, "dev-001", pass_command())
        if still_no_green.returncode == 0:
            print(still_no_green.stdout)
            print("Expected an unexpectedly-passing red run to not unlock the green stage.")
            return 1
        invalid_red = run_test(harness, workspace, root, "dev-001", import_error_command(), stage="red")
        if invalid_red.returncode == 0:
            print(invalid_red.stdout)
            print("Expected an import-error red run to be rejected as the wrong failure reason.")
            return 1
        green_after_invalid_red = run_test(harness, workspace, root, "dev-001", pass_command())
        if green_after_invalid_red.returncode == 0:
            print(green_after_invalid_red.stdout)
            print("Expected an invalid red run to not unlock the green stage.")
            return 1
        red = run_test(harness, workspace, root, "dev-001", fail_command(), stage="red")
        if red.returncode != 0:
            print(red.stdout)
            print("Expected a failing red-stage run to record TDD evidence.")
            return 1
        (workspace / "unplanned.txt").write_text("scope drift\n", encoding="utf-8")
        drift_green = run_test(harness, workspace, root, "dev-001", pass_command())
        if drift_green.returncode == 0:
            print(drift_green.stdout)
            print("Expected unit green to be rejected when the diff drifts outside declared scope.")
            return 1
        drift_state = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not drift_state.get("blockers"):
            print(json.dumps(drift_state, indent=2))
            print("Expected scope drift to add a loop blocker.")
            return 1
        (workspace / "unplanned.txt").unlink()
        resolved_scope = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "resolve-blocker", "--reason", "Removed the unplanned scope drift file."])
        if resolved_scope.returncode != 0:
            print(resolved_scope.stdout)
            print("Expected resolving scope drift blocker to pass.")
            return 1
        (workspace / "app.txt").write_text("tdd feature\n", encoding="utf-8")
        green = run_test(harness, workspace, root, "dev-001", pass_command())
        if green.returncode != 0:
            print(green.stdout)
            print("Expected the green stage to pass after red evidence exists.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        to_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if to_review.returncode != 0:
            print(to_review.stdout)
            print("Expected implementation_review to open after red evidence, green pass, and spec merge.")
            return 1

    with test_workspace(prefix="codex-dev-loop-worktree-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        (root / "development-plan.md").write_text(DEV_PLAN_TDD_RED, encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        worktree = tmp / "wt-dev-001"
        must(["git", "worktree", "add", str(worktree), "-b", "codex/wt-dev-001"], workspace)
        not_a_worktree = tmp / "plain-dir"
        not_a_worktree.mkdir()
        red_meta = run_bundled_test_gate("dev-001", fail_command(), worktree)
        rejected = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-test", "--unit", "dev-001", "--meta", str(red_meta), "--worktree", str(not_a_worktree)]
        )
        if rejected.returncode == 0:
            print(rejected.stdout)
            print("Expected record-test to reject a directory that is not a linked worktree.")
            return 1
        recorded_red = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-test", "--unit", "dev-001", "--meta", str(red_meta), "--worktree", str(worktree), "--stage", "red", "--expected-failure", "intentional missing behavior"]
        )
        if recorded_red.returncode != 0:
            print(recorded_red.stdout)
            print("Expected record-test to record red evidence from the worktree.")
            return 1
        (worktree / "app.txt").write_text("worktree feature\n", encoding="utf-8")
        must(["git", "add", "app.txt"], worktree)
        must(["git", "commit", "-m", "feat: unit dev-001"], worktree)
        green_meta = run_bundled_test_gate("dev-001", pass_command(), worktree)
        recorded_green = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-test", "--unit", "dev-001", "--meta", str(green_meta), "--worktree", str(worktree)]
        )
        if recorded_green.returncode != 0:
            print(recorded_green.stdout)
            print("Expected record-test to record green evidence from the worktree.")
            return 1
        must(["git", "merge", "--no-edit", "codex/wt-dev-001"], workspace)
        (workspace / "app.txt").write_text("worktree feature\nintegration tweak\n", encoding="utf-8")
        stale_worktree_green = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if stale_worktree_green.returncode == 0:
            print(stale_worktree_green.stdout)
            print("Expected interim worktree evidence to not satisfy the final gate after the main tree diverged.")
            return 1
        missing_integrator = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "verify-units"])
        if missing_integrator.returncode == 0:
            print(missing_integrator.stdout)
            print("Expected verify-units to require merge-integrator after merging worktree evidence.")
            return 1
        merge_review = record_review(harness, workspace, root, tmp, "merge-integrator", MERGE_INTEGRATOR_REVIEW_BODY)
        if merge_review.returncode != 0:
            print(merge_review.stdout)
            print("Expected merge-integrator review to be recorded after merging worktree branches.")
            return 1
        verified = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "verify-units"])
        if verified.returncode != 0:
            print(verified.stdout)
            print("Expected verify-units to re-run every unit gate in the main workspace.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        to_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if to_review.returncode != 0:
            print(to_review.stdout)
            print("Expected implementation_review to open after verify-units and spec merge.")
            return 1

    with test_workspace(prefix="codex-dev-loop-spec-merge-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        ambiguous = SPEC_DELTA_CAPABILITY + "\n## No Spec Impact\n\nAlso claiming no impact.\n"
        (root / "spec-delta.md").write_text(ambiguous, encoding="utf-8")
        ambiguous_check = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if ambiguous_check.returncode == 0:
            print(ambiguous_check.stdout)
            print("Expected an ambiguous spec-delta (capability changes plus no-impact) to fail validation.")
            return 1
        (root / "spec-delta.md").write_text(SPEC_DELTA_CAPABILITY, encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        missing_baseline = record_spec_merge(harness, workspace, root)
        if missing_baseline.returncode == 0:
            print(missing_baseline.stdout)
            print("Expected record-spec-merge to fail while the capability baseline file is missing.")
            return 1
        specs_dir = workspace / "specs"
        specs_dir.mkdir()
        (specs_dir / "app-core.md").write_text(SPEC_BASELINE_APP_CORE, encoding="utf-8")
        (workspace / "app.txt").write_text("spec feature\n", encoding="utf-8")
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        to_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if to_review.returncode != 0:
            print(to_review.stdout)
            print("Expected implementation_review to open after the spec baseline merge.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        (root / "spec-delta.md").write_text(SPEC_DELTA_REMOVED, encoding="utf-8")
        removed_still_present = record_spec_merge(harness, workspace, root)
        if removed_still_present.returncode == 0:
            print(removed_still_present.stdout)
            print("Expected record-spec-merge to fail while a REMOVED requirement is still in the baseline.")
            return 1

    with test_workspace(prefix="codex-dev-loop-scale-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp, extra_init_args=["--scale", "small"])
        (root / "test-plan.md").write_text("# Test Plan\n\n## Unit Tests\n\n## Integration Tests\n\n## E2E Or Browser Tests\n\n## Static Gates\n\n## Manual Checks\n\n## Coverage Gaps\n", encoding="utf-8")
        (root / "risk-analysis.md").write_text("# Risk Analysis\n\n## Correctness Risks\n\n## Security Risks\n\n## Data Or Migration Risks\n\n## Architecture Risks\n\n## Compatibility Risks\n\n## External Service Or Credential Risks\n\n## Mitigations\n", encoding="utf-8")
        relaxed = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if relaxed.returncode != 0:
            print(relaxed.stdout)
            print("Expected small scale to accept condensed test-plan and risk-analysis artifacts.")
            return 1
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("small feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        missing_docs_impact = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        if missing_docs_impact.returncode == 0:
            print(missing_docs_impact.stdout)
            print("Expected quality_gate to require docs-impact-reviewer after implementation review.")
            return 1
        docs_needed = record_review(harness, workspace, root, tmp, "docs-impact-reviewer", DOCS_NEEDED_REVIEW_BODY)
        if docs_needed.returncode == 0:
            print(docs_needed.stdout)
            print("Expected docs-needed to be recorded but not treated as a passing docs-impact decision.")
            return 1
        docs_needed_blocked = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        if docs_needed_blocked.returncode == 0:
            print(docs_needed_blocked.stdout)
            print("Expected docs-needed decision to keep quality_gate blocked until docs are updated and re-reviewed.")
            return 1
        docs = record_docs_impact(harness, workspace, root, tmp)
        if docs.returncode != 0:
            print(docs.stdout)
            print("Expected docs-impact-reviewer no-docs-needed decision to record.")
            return 1
        skip_clean = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        if skip_clean.returncode != 0:
            print(skip_clean.stdout)
            print("Expected small scale to skip risk_review for a non-sensitive change set after docs-impact-reviewer passes.")
            return 1
        small_review_validation = run(
            [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "validate", "--require-reviews"]
        )
        if small_review_validation.returncode != 0:
            print(small_review_validation.stdout)
            print("Expected validation to honor the small-scale risk-review skip.")
            return 1

    with test_workspace(prefix="codex-dev-loop-large-artifact-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp, extra_init_args=["--scale", "large"])
        (root / "risk-analysis.md").write_text(
            ARTIFACTS["risk-analysis.md"].replace("## Security Risks\n\nNo new security surface.", "## Security Risks\n"),
            encoding="utf-8",
        )
        incomplete_large = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if incomplete_large.returncode == 0:
            print(incomplete_large.stdout)
            print("Expected large scale to reject an empty Security Risks section.")
            return 1

    with test_workspace(prefix="codex-dev-loop-scale-guard-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp, extra_init_args=["--scale", "small"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("guarded feature\n", encoding="utf-8")
        (workspace / "package.json").write_text("{}\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        sensitive_green = run_test(harness, workspace, root, "dev-001", pass_command())
        if sensitive_green.returncode == 0:
            print(sensitive_green.stdout)
            print("Expected scope-check to refuse sensitive dependency manifest drift at unit green.")
            return 1
        sensitive_state = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not sensitive_state.get("blockers"):
            print(json.dumps(sensitive_state, indent=2))
            print("Expected sensitive scope drift to add a blocker.")
            return 1

    with test_workspace(prefix="codex-dev-loop-config-migration-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        v1_config = tmp / "v1.json"
        v1_config.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown"],
                    "quality_profile": "standard",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=v1_config)
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        migrated = state_data.get("config", {})
        if migrated.get("schema_version") != 4 or migrated.get("default_scale") != "standard" or migrated.get("spec_dir") != "specs":
            print(json.dumps(migrated, indent=2))
            print("Expected schema v1 config to migrate to v4 defaults at init.")
            return 1
        if migrated.get("max_test_retries_per_unit") != 3 or migrated.get("max_units") != 8 or migrated.get("max_diff_lines") != 1200:
            print(json.dumps(migrated, indent=2))
            print("Expected schema v1 config to migrate to budget defaults.")
            return 1

    with test_workspace(prefix="codex-dev-loop-budget-units-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "budget-units.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "risk_mode": "stop_and_ask",
                    "max_units": 1,
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        append_dev_002(root)
        too_many_units = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        if too_many_units.returncode == 0:
            print(too_many_units.stdout)
            print("Expected max_units budget to block a plan with too many units.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not any("max_units" in item for item in state_data.get("blockers", [])):
            print(json.dumps(state_data.get("blockers", []), indent=2))
            print("Expected max_units budget blocker to be recorded.")
            return 1

    with test_workspace(prefix="codex-dev-loop-budget-review-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "budget-review.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "risk_mode": "stop_and_ask",
                    "max_review_iterations": 1,
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        first_plan_review = record_review(harness, workspace, root, tmp, "plan-reviewer", PLAN_REVIEW_BODY)
        if first_plan_review.returncode != 0:
            print(first_plan_review.stdout)
            print("Expected first plan-reviewer iteration to fit the budget.")
            return 1
        second_plan_review = record_review(harness, workspace, root, tmp, "plan-reviewer", PLAN_REVIEW_BODY)
        if second_plan_review.returncode == 0:
            print(second_plan_review.stdout)
            print("Expected max_review_iterations budget to block another plan-reviewer iteration.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not any("max_review_iterations" in item for item in state_data.get("blockers", [])):
            print(json.dumps(state_data.get("blockers", []), indent=2))
            print("Expected max_review_iterations budget blocker to be recorded.")
            return 1

    with test_workspace(prefix="codex-dev-loop-budget-diff-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "budget-diff.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "risk_mode": "stop_and_ask",
                    "max_files_changed": 1,
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        (root / "technical-design.md").write_text(ARTIFACTS["technical-design.md"].replace("- app.txt", "- app.txt\n- second.txt"), encoding="utf-8")
        (root / "development-plan.md").write_text(ARTIFACTS["development-plan.md"].replace("- Scope: app.txt", "- Scope: app.txt, second.txt"), encoding="utf-8")
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("budget feature\n", encoding="utf-8")
        (workspace / "second.txt").write_text("budget second file\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        over_file_budget = run_test(harness, workspace, root, "dev-001", pass_command())
        if over_file_budget.returncode == 0:
            print(over_file_budget.stdout)
            print("Expected max_files_changed budget to block a green run with too many changed files.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not any("max_files_changed" in item for item in state_data.get("blockers", [])):
            print(json.dumps(state_data.get("blockers", []), indent=2))
            print("Expected max_files_changed budget blocker to be recorded.")
            return 1

    with test_workspace(prefix="codex-dev-loop-budget-untracked-lines-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "budget-lines.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "max_diff_lines": 5,
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        (root / "technical-design.md").write_text(
            ARTIFACTS["technical-design.md"].replace("- app.txt", "- app.txt\n- large-new.txt"), encoding="utf-8"
        )
        (root / "development-plan.md").write_text(
            ARTIFACTS["development-plan.md"].replace("- Scope: app.txt", "- Scope: app.txt, large-new.txt"), encoding="utf-8"
        )
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "large-new.txt").write_text("\n".join(f"line {index}" for index in range(10)) + "\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        over_line_budget = run_test(harness, workspace, root, "dev-001", pass_command())
        if over_line_budget.returncode == 0:
            print(over_line_budget.stdout)
            print("Expected max_diff_lines to count and block a large untracked source file.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not any("max_diff_lines" in item for item in state_data.get("blockers", [])):
            print(json.dumps(state_data.get("blockers", []), indent=2))
            print("Expected max_diff_lines blocker to be recorded for untracked content.")
            return 1

    with test_workspace(prefix="codex-dev-loop-gate-resolution-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        priority_home = tmp / "loop-home"
        companion = priority_home / "skills" / "automated-dev-executor" / "scripts" / "test_gate.py"
        companion.parent.mkdir(parents=True)
        companion_marker = tmp / "companion-ran.txt"
        bundled_gate = (SCRIPTS_ROOT / "test_gate.py").resolve()
        companion.write_text(
            "import runpy, sys\nfrom pathlib import Path\n"
            f"Path({str(companion_marker)!r}).write_text('ran', encoding='utf-8')\n"
            f"sys.argv[0] = {str(bundled_gate)!r}\n"
            f"runpy.run_path({str(bundled_gate)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        env = {**os.environ, "CODEX_DEV_LOOP_HOME": str(priority_home)}
        workspace = tmp / "repo"
        workspace.mkdir()
        init_git_repo(workspace)
        root = workspace / ".codex" / "dev-loop"
        source = write_source(tmp)
        base = [sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root)]
        result = run([*base, "init", "--source", str(source)], env=env)
        if result.returncode != 0:
            print(result.stdout)
            print("Expected gate-resolution loop setup to pass.")
            return 1
        record_requirements_review(harness, workspace, root, tmp, env=env)
        result = run([*base, "set-phase", "planning"], env=env)
        if result.returncode != 0:
            print(result.stdout)
            print("Expected gate-resolution loop setup to pass.")
            return 1
        write_artifacts(root)
        for step in ([*base, "set-phase", "plan_review"],):
            result = run(step, env=env)
            if result.returncode != 0:
                print(result.stdout)
                return 1
        agent_id = "019f-plan-reviewer"
        report = write_review(tmp, "plan-review.md", "plan-reviewer", agent_id, root, workspace, PLAN_REVIEW_BODY)
        result = run([*base, "record-review", "--role", "plan-reviewer", "--agent-id", agent_id, "--report", str(report)], env=env)
        if result.returncode != 0:
            print(result.stdout)
            return 1
        for step in (
            [*base, "set-phase", "branch"],
            [*base, "record-branch", "--branch", "codex/test"],
            [*base, "set-phase", "implementation"],
        ):
            result = run(step, env=env)
            if result.returncode != 0:
                print(result.stdout)
                return 1
        gate_run = run([*base, "run-test", "--unit", "dev-001", "--command", pass_command()], env=env)
        if gate_run.returncode != 0:
            print(gate_run.stdout)
            print("Expected run-test to pass via the relocated companion test gate.")
            return 1
        if not companion_marker.exists():
            print("Expected the companion skill test gate under CODEX_DEV_LOOP_HOME to take priority over the bundled fallback.")
            return 1

    with test_workspace(prefix="codex-dev-loop-all-units-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        append_dev_002(root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        run_test(harness, workspace, root, "dev-002", fail_command())
        blocked = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if blocked.returncode == 0:
            print(blocked.stdout)
            print("Expected implementation_review transition to fail until every planned unit passes.")
            return 1

    with test_workspace(prefix="codex-dev-loop-quality-failure-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        blocked_without_spec_merge = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if blocked_without_spec_merge.returncode == 0:
            print(blocked_without_spec_merge.stdout)
            print("Expected implementation_review transition to require record-spec-merge.")
            return 1
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        docs = record_docs_impact(harness, workspace, root, tmp)
        if docs.returncode != 0:
            print(docs.stdout)
            print("Expected docs-impact-reviewer no-docs-needed decision to record before quality gate.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        failing_quality = run_failing_quality(harness, workspace, root, tmp / "failing-quality")
        if failing_quality.returncode == 0:
            print(failing_quality.stdout)
            print("Expected failing ai-code-quality-gate process to block.")
            return 1

    with test_workspace(prefix="codex-dev-loop-budget-quality-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "budget-quality.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "pr_without_merge",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "standard",
                    "risk_mode": "stop_and_ask",
                    "max_quality_fix_rounds": 1,
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        docs = record_docs_impact(harness, workspace, root, tmp)
        if docs.returncode != 0:
            print(docs.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        first_quality_failure = run_failing_quality(harness, workspace, root, tmp / "first-quality-failure")
        if first_quality_failure.returncode == 0:
            print(first_quality_failure.stdout)
            print("Expected first failing quality run to fail normally.")
            return 1
        resolved = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "resolve-blocker", "--reason", "quality failure acknowledged for budget retry test"])
        if resolved.returncode != 0:
            print(resolved.stdout)
            print("Expected quality blocker to be resolvable for retry budget test.")
            return 1
        over_quality_budget = run_failing_quality(harness, workspace, root, tmp / "second-quality-failure")
        if over_quality_budget.returncode == 0:
            print(over_quality_budget.stdout)
            print("Expected max_quality_fix_rounds budget to block another quality run.")
            return 1
        state_data = json.loads((root / "loop-state.json").read_text(encoding="utf-8"))
        if not any("max_quality_fix_rounds" in item for item in state_data.get("blockers", [])):
            print(json.dumps(state_data.get("blockers", []), indent=2))
            print("Expected max_quality_fix_rounds budget blocker to be recorded.")
            return 1
    with test_workspace(prefix="codex-dev-loop-quality-floor-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        docs = record_docs_impact(harness, workspace, root, tmp)
        if docs.returncode != 0:
            print(docs.stdout)
            print("Expected docs-impact-reviewer no-docs-needed decision to record before quality gate.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        reduced_quality = run_quality(harness, workspace, root, tmp / "reduced-quality", require="test", gate_names=["test"])
        if reduced_quality.returncode == 0:
            print(reduced_quality.stdout)
            print("Expected --require test to add to, not replace, configured standard quality gates.")
            return 1

    with test_workspace(prefix="codex-dev-loop-commit-only-test-") as raw_tmp:
        tmp = Path(raw_tmp)
        config_path = tmp / "commit-only.json"
        config_path.write_text(
            json.dumps(
                {
                    "automation_level": "commit_only",
                    "source_types": ["markdown", "notion"],
                    "quality_profile": "light",
                    "test_failure_limit": 3,
                    "risk_mode": "stop_and_ask",
                }
            ),
            encoding="utf-8",
        )
        workspace, root = init_loop(harness, tmp, config_path=config_path)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("commit-only feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            return 1
        docs = record_docs_impact(harness, workspace, root, tmp)
        if docs.returncode != 0:
            print(docs.stdout)
            print("Expected docs-impact-reviewer no-docs-needed decision to record before quality gate.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        quality = run_quality(harness, workspace, root, tmp / "commit-only-quality")
        if quality.returncode != 0:
            print(quality.stdout)
            print("Expected commit_only quality gate to pass.")
            return 1
        must(["git", "add", "app.txt"], workspace)
        must(["git", "commit", "-m", "feat: commit-only feature"], workspace)
        record_commit = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-commit"])
        if record_commit.returncode != 0:
            print(record_commit.stdout)
            print("Expected record-commit to pass after quality gate and git commit.")
            return 1
        complete_commit_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if complete_commit_only.returncode != 0:
            print(complete_commit_only.stdout)
            print("Expected commit_only automation config to allow completion after recorded commit.")
            return 1
        validate_commit_only = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "validate", "--require-reviews", "--require-final"])
        if validate_commit_only.returncode != 0:
            print(validate_commit_only.stdout)
            print("Expected commit_only final validation to require commit but not PR/cloud records.")
            return 1
        wrapper_validate_commit_only = run([sys.executable, str(validator), "--workspace", str(workspace), "--root", str(root), "--require-final"])
        if wrapper_validate_commit_only.returncode != 0:
            print(wrapper_validate_commit_only.stdout)
            print("Expected legacy validator to reuse commit_only harness final validation.")
            return 1
        blocked_pr = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "pr"])
        if blocked_pr.returncode == 0:
            print(blocked_pr.stdout)
            print("Expected commit_only automation config to block PR phase.")
            return 1

    with test_workspace(prefix="codex-dev-loop-happy-path-") as raw_tmp:
        tmp = Path(raw_tmp)
        workspace, root = init_loop(harness, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "plan_review"])
        record_plan_review(harness, workspace, root, tmp)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "branch"])
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-branch", "--branch", "codex/test"])
        (workspace / "app.txt").write_text("feature\n", encoding="utf-8")
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())

        (workspace / "app.txt").write_text("feature changed after test\n", encoding="utf-8")
        stale_test = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if stale_test.returncode == 0:
            print(stale_test.stdout)
            print("Expected code changes after tests to stale test evidence.")
            return 1
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            print("Expected implementation review to record.")
            return 1

        (workspace / "app.txt").write_text("feature changed after implementation review\n", encoding="utf-8")
        stale_review = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        if stale_review.returncode == 0:
            print(stale_review.stdout)
            print("Expected code changes after implementation review to stale review evidence.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        run_test(harness, workspace, root, "dev-001", pass_command())
        must_record_spec_merge(harness, workspace, root)
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        impl = record_review(harness, workspace, root, tmp, "implementation-reviewer", IMPLEMENTATION_REVIEW_BODY)
        if impl.returncode != 0:
            print(impl.stdout)
            return 1

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "risk_review"])
        risk = record_review(harness, workspace, root, tmp, "risk-reviewer", RISK_REVIEW_BODY)
        if risk.returncode != 0:
            print(risk.stdout)
            print("Expected risk review to record.")
            return 1

        docs = record_docs_impact(harness, workspace, root, tmp)
        if docs.returncode != 0:
            print(docs.stdout)
            print("Expected docs-impact-reviewer no-docs-needed decision to record before quality gate.")
            return 1
        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "quality_gate"])
        fake_quality_script = tmp / "fake-quality-gate.py"
        fake_quality_script.write_text("print('fake')\n", encoding="utf-8")
        fake_script_attempt = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "run-quality",
                "--quality-gate-script",
                str(fake_quality_script),
                "--out-dir",
                str(tmp / "fake-script-quality"),
            ]
        )
        if fake_script_attempt.returncode == 0:
            print(fake_script_attempt.stdout)
            print("Expected caller-supplied quality gate script to be rejected.")
            return 1
        old_record_quality = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-quality"])
        if old_record_quality.returncode == 0:
            print(old_record_quality.stdout)
            print("Expected removed record-quality command to fail.")
            return 1
        stale_quality_dir = tmp / "prefilled-quality"
        write_prefilled_quality_dir(stale_quality_dir)
        stale_quality = run_quality(harness, workspace, root, stale_quality_dir)
        if stale_quality.returncode == 0:
            print(stale_quality.stdout)
            print("Expected run-quality to reject pre-existing out-dir artifacts.")
            return 1
        fake_home, fake_marker = write_fake_codex_home(tmp)
        fake_env = {**os.environ, "CODEX_HOME": str(fake_home)}
        quality = run_quality(harness, workspace, root, tmp / "quality-run", env=fake_env)
        if quality.returncode != 0:
            print(quality.stdout)
            print("Expected real ai-code-quality-gate run to pass even when CODEX_HOME is fake.")
            return 1
        if fake_marker.exists():
            print("Expected run-quality to ignore CODEX_HOME fake quality gate script.")
            return 1

        must(["git", "add", "app.txt"], workspace)
        must(["git", "commit", "-m", "feat: self-test feature"], workspace)
        commit = run(["git", "rev-parse", "HEAD"], workspace).stdout.strip()

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "pr"])
        pr_url = "https://github.com/example/repo/pull/1"
        pr_evidence = tmp / "pr-evidence.json"
        pr_evidence.write_text(
            json.dumps({"url": pr_url, "headRefName": "codex/test", "headRefOid": commit, "state": "OPEN", "baseRepository": {"nameWithOwner": "example/repo"}}),
            encoding="utf-8",
        )
        production_env = {**os.environ}
        production_env.pop("CODEX_DEV_LOOP_TEST_MODE", None)
        simulated_pr_without_test_mode = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                commit,
                "--pr-url",
                pr_url,
                "--evidence",
                str(pr_evidence),
                "--allow-local-simulation",
            ],
            env=production_env,
        )
        if simulated_pr_without_test_mode.returncode == 0:
            print(simulated_pr_without_test_mode.stdout)
            print("Expected local PR simulation to be rejected outside CODEX_DEV_LOOP_TEST_MODE.")
            return 1
        bad_pr = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                "badcommit",
                "--pr-url",
                pr_url,
                "--evidence",
                str(pr_evidence),
                "--allow-local-simulation",
            ]
        )
        if bad_pr.returncode == 0:
            print(bad_pr.stdout)
            print("Expected PR record with wrong commit to fail.")
            return 1
        wrong_repo_pr_evidence = tmp / "wrong-repo-pr-evidence.json"
        wrong_repo_pr_evidence.write_text(
            json.dumps(
                {
                    "url": "https://github.com/example/other/pull/1",
                    "headRefName": "codex/test",
                    "headRefOid": commit,
                    "state": "OPEN",
                    "baseRepository": {"nameWithOwner": "example/other"},
                }
            ),
            encoding="utf-8",
        )
        wrong_repo_pr = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                commit,
                "--pr-url",
                "https://github.com/example/other/pull/1",
                "--evidence",
                str(wrong_repo_pr_evidence),
                "--allow-local-simulation",
            ]
        )
        if wrong_repo_pr.returncode == 0:
            print(wrong_repo_pr.stdout)
            print("Expected PR evidence for a different GitHub repository to fail.")
            return 1
        pr = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-pr",
                "--branch",
                "codex/test",
                "--commit",
                commit,
                "--pr-url",
                pr_url,
                "--evidence",
                str(pr_evidence),
                "--allow-local-simulation",
            ]
        )
        if pr.returncode != 0:
            print(pr.stdout)
            print("Expected PR record to pass.")
            return 1

        run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "cloud_checks"])
        bad_cloud_evidence = tmp / "bad-cloud-evidence.json"
        bad_cloud_evidence.write_text(json.dumps([{"name": "ai-quality-gate", "state": "success"}]), encoding="utf-8")
        simulated_cloud_without_test_mode = run(
            [
                sys.executable,
                str(harness),
                "--workspace",
                str(workspace),
                "--root",
                str(root),
                "record-cloud",
                "--status",
                "passed",
                "--evidence",
                str(bad_cloud_evidence),
                "--allow-local-simulation",
            ],
            env=production_env,
        )
        if simulated_cloud_without_test_mode.returncode == 0:
            print(simulated_cloud_without_test_mode.stdout)
            print("Expected local cloud simulation to be rejected outside CODEX_DEV_LOOP_TEST_MODE.")
            return 1
        standard_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(bad_cloud_evidence), "--allow-local-simulation"])
        if standard_cloud.returncode != 0:
            print(standard_cloud.stdout)
            print("Expected standard cloud checks to pass without a third-party AI review service.")
            return 1
        completed_cloud_evidence = tmp / "completed-cloud-evidence.json"
        completed_cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "ai-quality-gate", "state": "completed"},
                    {"name": "qodo-pr-agent", "state": "success"},
                ]
            ),
            encoding="utf-8",
        )
        completed_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(completed_cloud_evidence), "--allow-local-simulation"])
        if completed_cloud.returncode == 0:
            print(completed_cloud.stdout)
            print("Expected completed-without-success cloud check state to fail.")
            return 1
        substring_cloud_evidence = tmp / "substring-cloud-evidence.json"
        substring_cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "not-ai-quality-gate", "state": "success"},
                    {"name": "qodo-pr-agent", "state": "success"},
                ]
            ),
            encoding="utf-8",
        )
        substring_cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(substring_cloud_evidence), "--allow-local-simulation"])
        if substring_cloud.returncode == 0:
            print(substring_cloud.stdout)
            print("Expected cloud checks to require exact canonical names, not substring matches.")
            return 1
        cloud_evidence = tmp / "cloud-evidence.json"
        cloud_evidence.write_text(
            json.dumps(
                [
                    {"name": "ai-quality-gate", "state": "success"},
                    {"name": "Semgrep OSS Scan", "state": "success"},
                    {"name": "CodeQL", "state": "success"},
                    {"name": "SonarCloud Code Analysis", "state": "success"},
                    {"name": "Qodana Scan", "state": "success"},
                    {"name": "subagent-alignment", "state": "success"},
                    {"name": "qodo-pr-agent", "state": "success"},
                    {"name": "optional-flaky-check", "state": "failure"},
                ]
            ),
            encoding="utf-8",
        )
        cloud = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "record-cloud", "--status", "passed", "--evidence", str(cloud_evidence), "--allow-local-simulation"])
        if cloud.returncode != 0:
            print(cloud.stdout)
            print("Expected cloud checks to pass.")
            return 1

        complete = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "complete"])
        if complete.returncode != 0:
            print(complete.stdout)
            print("Expected transition to complete to pass after all prerequisites.")
            return 1

        back = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation"])
        if back.returncode != 0:
            print(back.stdout)
            print("Expected backtrack to implementation to pass.")
            return 1
        stale_after_backtrack = run([sys.executable, str(harness), "--workspace", str(workspace), "--root", str(root), "set-phase", "implementation_review"])
        if stale_after_backtrack.returncode == 0:
            print(stale_after_backtrack.stdout)
            print("Expected backtrack to clear stale test evidence before implementation review.")
            return 1

    print("codex-dev-loop loop integration suite passed")
    return 0


@pytest.mark.integration
@pytest.mark.slow
def test_loop_integration() -> None:
    configure_test_environment()
    assert _run_loop_integration_suite() == 0
