"""Full-loop state-machine command handlers."""

from __future__ import annotations
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from .contracts import CORE_VERSION, EVIDENCE_SCHEMA_VERSION
from .evidence import (
    EvidenceContractError,
    load_evidence_document,
    normalize_evidence_document,
    write_evidence_document,
)

from .settings import (
    BUNDLED_QUALITY_GATE_SCRIPT,
    BUNDLED_TEST_GATE_SCRIPT,
    DOCS_IMPACT_REVIEWER_ROLE,
    DRAFT_SOURCE_TEMPLATE,
    MERGE_INTEGRATOR_ROLE,
    PHASES,
    PHASE_INDEX,
    PROTECTED_BRANCHES,
    REQUIREMENTS_REVIEWER_ROLE,
    REVIEW_ROLES,
    SCALES,
    SCALE_INDEX,
    TEMPLATES,
    TEST_STAGES,
    default_quality_gate_script,
    default_test_gate_script,
    load_loop_config,
    loop_config,
    loop_scale,
    merge_unique,
    now,
    quality_profile,
    split_csv,
)
from .workspace import (
    add_blocker,
    all_planned_tests_passed,
    assert_config_allows_phase,
    assert_no_blockers,
    assert_test_mode,
    attempt_stage,
    current_git_branch,
    current_git_head,
    evidence_fingerprint,
    git_origin_repository,
    has_worktree_evidence,
    increment_quality_failure_round,
    increment_review_iteration,
    is_git_repo,
    missing_or_failing_units,
    parse_key_value_output,
    phase,
    plan_fingerprint,
    planned_units,
    read_state,
    required_review_roles,
    run_budget_check_hook,
    run_child,
    run_git,
    run_quality_budget_hook,
    run_review_budget_hook,
    run_scope_check_hook,
    sha256_bytes,
    source_fingerprint,
    unit_red_gate_satisfied,
    valid_review_decisions,
    workspace_fingerprint,
    write_state,
)
from .specs import (
    load_spec_delta,
    spec_delta_baseline_problems,
)
from .validation import (
    assert_core_artifacts,
    assert_phase,
    assert_phase_prereqs,
    assert_transition,
    clear_downstream_state,
    cloud_is_current,
    copy_report,
    git_commit_is_current,
    git_pr_is_current,
    load_json_file,
    load_test_meta,
    parse_decision,
    parse_quality_decision,
    quality_decision_allows_progress,
    quality_is_current,
    review_is_current,
    run_gh_json,
    validate_agent_id,
    validate_cloud_evidence,
    validate_pr_evidence,
    validate_quality_results,
    validate_red_failure,
    validate_review_report,
)

def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    state_path = root / "loop-state.json"
    if state_path.exists() and not args.force:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        raise SystemExit(
            f"A previous dev loop exists at {root} (phase: {previous.get('phase', 'unknown')}). "
            "Archive it first (harness archive) or pass --force to overwrite its state."
        )
    root.mkdir(parents=True, exist_ok=True)
    config = load_loop_config(args.config)
    if args.source_type not in config["source_types"]:
        raise SystemExit(f"Configured source_types do not allow {args.source_type!r} sources.")
    scale = args.scale or config["default_scale"]
    if scale not in SCALE_INDEX:
        raise SystemExit(f"Unknown scale: {scale!r}; use one of: {', '.join(SCALES)}.")
    source = Path(args.source) if args.source else None
    if source and source.exists():
        shutil.copyfile(source, root / "source.md")
    elif not (root / "source.md").exists():
        if args.draft:
            (root / "source.md").write_text(DRAFT_SOURCE_TEMPLATE, encoding="utf-8")
        else:
            raise SystemExit(
                "A source spec is required. Pass --source <source.md>, create source.md first, "
                "or start a clarification-first loop with --draft."
            )

    for name, text in TEMPLATES.items():
        path = root / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")

    state = {
        "phase": "intake",
        "created_at": now(),
        "updated_at": now(),
        "config": config,
        "scale": scale,
        "source": str(source) if source else "",
        "source_type": args.source_type,
        "source_fingerprint": source_fingerprint(root),
        "reviews": {},
        "test_attempts": {},
        "quality_gate": {},
        "git": {},
        "github_actions": {},
        "blockers": [],
    }
    write_state(root, state)
    print(f"Initialized dev loop at {root} (phase: intake, scale: {scale})")
    print("Clarify Goal and Acceptance Criteria with the user, record Q&A in clarification-log.md, run requirements-reviewer, then set-phase planning.")
    return 0


def cmd_set_phase(args: argparse.Namespace) -> int:
    if args.phase not in PHASES:
        raise SystemExit(f"Unknown phase: {args.phase}")
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_config_allows_phase(state, args.phase)
    target_index = PHASE_INDEX[args.phase]
    if not run_budget_check_hook(
        root,
        workspace,
        state,
        f"before phase {args.phase}",
        include_diff=target_index >= PHASE_INDEX["implementation"],
        include_units=target_index >= PHASE_INDEX["plan_review"],
    ):
        write_state(root, state)
        return 1
    assert_transition(root, state, args.phase, workspace)
    if PHASE_INDEX[args.phase] < PHASE_INDEX[phase(state)]:
        clear_downstream_state(state, args.phase)
    state["phase"] = args.phase
    write_state(root, state)
    print(f"Phase set to {args.phase}")
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    fingerprints = {
        "source_fingerprint": source_fingerprint(root),
        "plan_fingerprint": plan_fingerprint(root),
        "workspace_fingerprint": workspace_fingerprint(workspace),
    }
    if args.json:
        print(json.dumps(fingerprints, sort_keys=True))
    else:
        print(f"SOURCE_FINGERPRINT={fingerprints['source_fingerprint']}")
        print(f"PLAN_FINGERPRINT={fingerprints['plan_fingerprint']}")
        print(f"WORKSPACE_FINGERPRINT={fingerprints['workspace_fingerprint']}")
    return 0


def cmd_record_review(args: argparse.Namespace) -> int:
    role = args.role
    if role not in REVIEW_ROLES:
        raise SystemExit(f"Unknown review role: {role}")
    validate_agent_id(args.agent_id)
    src = Path(args.report)
    if not src.exists():
        raise SystemExit(f"Review report does not exist: {src}")
    decision = parse_decision(src)
    if decision not in valid_review_decisions(role):
        expected = ", ".join(sorted(valid_review_decisions(role)))
        raise SystemExit(f"Review report has invalid or missing Decision: {src}; expected one of: {expected}")
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    validate_review_report(role, src, args.agent_id, root, workspace)
    if role == REQUIREMENTS_REVIEWER_ROLE:
        assert_phase(state, {"intake"})
    elif role == "plan-reviewer":
        assert_phase(state, {"planning", "plan_review"})
    elif role == MERGE_INTEGRATOR_ROLE:
        assert_phase(state, {"implementation"})
        if not has_worktree_evidence(state):
            raise SystemExit("merge-integrator is only recorded after one or more worktree test records exist.")
    elif role == DOCS_IMPACT_REVIEWER_ROLE:
        assert_phase(state, {"implementation_review", "risk_review"})
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot record docs-impact review before implementation-reviewer passes.")
    elif role == "implementation-reviewer":
        assert_phase(state, {"implementation", "implementation_review"})
        if not all_planned_tests_passed(root, state, workspace):
            missing = ", ".join(missing_or_failing_units(root, state, workspace))
            raise SystemExit(f"Cannot record implementation review before all planned test gates pass: {missing}")
    elif role == "risk-reviewer":
        assert_phase(state, {"implementation_review", "risk_review"})
        if not review_is_current(state, "implementation-reviewer", root, workspace):
            raise SystemExit("Cannot record risk review before implementation-reviewer passes.")
    if not run_review_budget_hook(root, workspace, state, role):
        write_state(root, state)
        return 1
    increment_review_iteration(state, role)
    dest = root / "reviews" / f"{role}.md"
    copy_report(src, dest)
    fingerprints = evidence_fingerprint(root, workspace)
    state["reviews"][role] = {
        "decision": decision,
        "path": str(dest),
        "agent_id": args.agent_id,
        "source_fingerprint": fingerprints["source"] if role == REQUIREMENTS_REVIEWER_ROLE else "",
        "plan_fingerprint": fingerprints["plan"] if role != REQUIREMENTS_REVIEWER_ROLE else "",
        "workspace_fingerprint": fingerprints["workspace"] if role not in {REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer"} else "",
        "report_fingerprint": sha256_bytes(dest.read_bytes()),
        "recorded_at": now(),
    }
    if decision == "block" or (role not in {REQUIREMENTS_REVIEWER_ROLE, "plan-reviewer", DOCS_IMPACT_REVIEWER_ROLE} and decision != "pass"):
        add_blocker(state, f"{role} returned {decision}")
        write_state(root, state)
        print(f"{role}: {decision}")
        return 1
    if role == DOCS_IMPACT_REVIEWER_ROLE and decision != "no-docs-needed":
        write_state(root, state)
        print(f"{role}: {decision}")
        return 1
    write_state(root, state)
    print(f"{role}: {decision}")
    return 0


def record_test_meta(
    root: Path,
    workspace: Path,
    state: dict,
    unit: str,
    meta_path: Path,
    stage: str = "green",
    run_cwd: Path | None = None,
    worktree: str = "",
    expected_failure: str = "",
) -> int:
    run_cwd = run_cwd or workspace
    meta = load_test_meta(meta_path, unit, run_cwd)
    attempts = state.setdefault("test_attempts", {}).setdefault(unit, [])
    record = {
        "status": meta["status"],
        "stage": stage,
        "command": meta["command"],
        "exit_code": meta.get("exit_code"),
        "log": meta["log_path"],
        "meta": str(meta_path),
        "plan_fingerprint": plan_fingerprint(root),
        "workspace_fingerprint": workspace_fingerprint(run_cwd),
        "recorded_at": now(),
    }
    if worktree:
        record["worktree"] = worktree
    if stage == "red":
        validation = validate_red_failure(unit, Path(meta["log_path"]), expected_failure, status=meta["status"])
        record["red_validation"] = validation
        attempts.append(record)
        write_state(root, state)
        if meta["status"] == "passed":
            print(
                f"{unit}: red-stage test PASSED before implementation. The test does not prove the missing behavior; "
                "strengthen it (or mark the unit '- TDD: regression-only' in the development plan and re-run plan review)."
            )
            return 1
        if meta["status"] != "failed":
            print(f"{unit}: red-stage run ended with {meta['status']}; fix the test harness so the red run fails cleanly.")
            return 1
        if validation["status"] != "pass":
            print(f"{unit}: red-stage failure rejected by red-test-validator ({validation['status']}): {validation['reason']}")
            return 1
        print(f"{unit}: red evidence recorded (attempt {len(attempts)}; red-test-validator pass)")
        return 0
    attempts.append(record)
    # test_failure_limit is the number of automatic retries allowed after a
    # failure: 0 blocks on the first failure, 3 blocks on the fourth
    # consecutive failure. Counting is consecutive (a pass resets it), skips
    # red-stage evidence runs, and also resets when a blocker is explicitly
    # resolved, so an early stumble does not count against a later,
    # unrelated regression.
    reset_marker = state.get("failure_counter_reset_at", "")
    consecutive_failures = 0
    for item in reversed(attempts):
        if attempt_stage(item) == "red":
            continue
        if item.get("status") == "passed":
            break
        if reset_marker and item.get("recorded_at", "") <= reset_marker:
            break
        consecutive_failures += 1
    configured_limit = loop_config(state)["max_test_retries_per_unit"]
    stop_after = configured_limit + 1
    if consecutive_failures >= stop_after and meta["status"] != "passed":
        add_blocker(
            state,
            f"{unit} test gate failed {consecutive_failures} consecutive time(s); configured retry limit is {configured_limit}",
        )
        write_state(root, state)
        print(f"{unit}: failed {consecutive_failures} consecutive time(s)")
        return 1
    if meta["status"] == "passed" and not run_scope_check_hook(root, workspace, state, f"{unit} green", run_cwd=run_cwd):
        write_state(root, state)
        print(f"{unit}: green test passed, but scope-check failed.")
        return 1
    if meta["status"] == "passed" and not run_budget_check_hook(root, workspace, state, f"{unit} green", run_cwd=run_cwd):
        write_state(root, state)
        print(f"{unit}: green test passed, but budget/time-box check failed.")
        return 1
    write_state(root, state)
    print(f"{unit}: {meta['status']} attempt {len(attempts)}")
    return 0


def resolve_test_gate_script(config: dict, caller_path: str = "") -> Path:
    """Trusted test gate scripts, in priority order: home-anchored config
    override, the automated-dev-executor companion skill, then the bundled
    fallback. Caller-supplied paths outside this set need test mode."""
    override = (config.get("test_gate_script") or "").strip() if config.get("home_anchored") else ""
    trusted: list[Path] = []
    if override:
        trusted.append(Path(override).expanduser())
    trusted.extend([default_test_gate_script(), BUNDLED_TEST_GATE_SCRIPT])
    if caller_path:
        candidate = Path(caller_path).expanduser()
        try:
            is_trusted = any(candidate.resolve() == item.resolve() for item in trusted)
        except OSError:
            is_trusted = False
        if not is_trusted:
            assert_test_mode("Caller-supplied test gate scripts")
        if not candidate.exists():
            raise SystemExit(f"Test gate script does not exist: {candidate}")
        return candidate
    for item in trusted:
        if item.exists():
            return item
    raise SystemExit(
        "No test gate script found. Install the automated-dev-executor skill, set test_gate_script in the "
        "codex-dev-loop config, or restore the bundled scripts/test_gate.py."
    )


def assert_green_stage_allowed(root: Path, state: dict, unit: str) -> None:
    if not unit_red_gate_satisfied(root, state, unit):
        raise SystemExit(
            f"Unit {unit} has no red-stage TDD evidence for the current plan. Run the test gate with --stage red "
            "against the new failing test first, or mark the unit '- TDD: regression-only' in development-plan.md "
            "before plan review."
        )


def run_test_gate(
    root: Path,
    workspace: Path,
    state: dict,
    unit: str,
    test_command: str,
    stage: str,
    timeout: int,
    script: Path,
    expected_failure: str = "",
) -> int:
    if stage == "green":
        assert_green_stage_allowed(root, state, unit)
    command = [
        sys.executable,
        str(script),
        "--unit",
        unit,
        "--command",
        test_command,
        "--cwd",
        str(workspace),
        "--timeout",
        str(timeout),
    ]
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    meta = parse_key_value_output(result.stdout, "AUTODEV_TEST_META")
    if not meta:
        raise SystemExit("Test gate did not report AUTODEV_TEST_META.")
    return record_test_meta(root, workspace, state, unit, Path(meta), stage=stage, expected_failure=expected_failure)


def cmd_run_test(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    if args.stage not in TEST_STAGES:
        raise SystemExit(f"Unknown test stage: {args.stage!r}; use red or green.")
    script = resolve_test_gate_script(loop_config(state), args.test_gate_script)
    return run_test_gate(root, workspace, state, args.unit, args.command, args.stage, args.timeout, script, expected_failure=args.expected_failure)


def is_linked_worktree(workspace: Path, candidate: Path) -> bool:
    completed = run_git(candidate, ["rev-parse", "--git-common-dir"])
    if completed.returncode != 0:
        return False
    common = Path(completed.stdout.strip())
    if not common.is_absolute():
        common = (candidate / common).resolve()
    try:
        return common.resolve() == (workspace / ".git").resolve()
    except OSError:
        return False


def cmd_record_test(args: argparse.Namespace) -> int:
    """Record a test gate run that a unit-implementer executed in an isolated
    git worktree. The orchestrator serializes these calls, so parallel units
    never race on loop-state.json. Worktree fingerprints intentionally differ
    from the main workspace: interim evidence never satisfies the final gate,
    which forces a post-merge verify-units pass in the main workspace."""
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    if args.stage not in TEST_STAGES:
        raise SystemExit(f"Unknown test stage: {args.stage!r}; use red or green.")
    worktree = Path(args.worktree).resolve()
    if not worktree.exists():
        raise SystemExit(f"Worktree does not exist: {worktree}")
    if worktree == workspace:
        raise SystemExit("record-test is for isolated worktrees; use run-test in the main workspace.")
    if not is_linked_worktree(workspace, worktree):
        raise SystemExit(f"{worktree} is not a linked git worktree of {workspace}; create it with 'git worktree add'.")
    if args.stage == "green":
        assert_green_stage_allowed(root, state, args.unit)
    return record_test_meta(
        root,
        workspace,
        state,
        args.unit,
        Path(args.meta),
        stage=args.stage,
        run_cwd=worktree,
        worktree=str(worktree),
        expected_failure=args.expected_failure,
    )


def cmd_verify_units(args: argparse.Namespace) -> int:
    """Re-run every planned unit's most recent green command in the main
    workspace. Run this after merging parallel worktrees back (and after the
    spec baseline merge), so the final per-unit evidence matches the exact
    tree that goes to review, quality gate, and PR."""
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    units = planned_units(root)
    if not units:
        raise SystemExit("development-plan.md has no '## Unit dev-*' sections to verify.")
    if has_worktree_evidence(state) and not review_is_current(state, MERGE_INTEGRATOR_ROLE, root, workspace):
        raise SystemExit("Cannot verify merged worktree units before merge-integrator passes for the current merged tree.")
    commands: dict[str, str] = {}
    missing: list[str] = []
    for unit in units:
        attempts = state.get("test_attempts", {}).get(unit, [])
        green_commands = [item.get("command") for item in attempts if attempt_stage(item) == "green" and item.get("command")]
        any_commands = [item.get("command") for item in attempts if item.get("command")]
        if green_commands:
            commands[unit] = green_commands[-1]
        elif any_commands:
            commands[unit] = any_commands[-1]
        else:
            missing.append(unit)
    if missing:
        raise SystemExit(
            "No recorded test command for unit(s): " + ", ".join(missing) + ". Run run-test or record-test for them first."
        )
    script = resolve_test_gate_script(loop_config(state), "")
    for unit in units:
        state = read_state(root)
        outcome = run_test_gate(root, workspace, state, unit, commands[unit], "green", args.timeout, script)
        if outcome != 0:
            print(f"verify-units stopped at {unit}.")
            return outcome
    print(f"verify-units: {len(units)} unit(s) re-verified in the main workspace.")
    return 0


def record_quality_result(
    root: Path,
    workspace: Path,
    state: dict,
    summary: Path,
    results: Path,
    command: list[str],
    exit_code: int,
    stdout: str,
    required_gates: list[str],
    profile_name: str,
) -> int:
    if exit_code != 0:
        stdout_dest = root / "quality-gate-stdout.log"
        stdout_dest.write_text(stdout, encoding="utf-8", errors="replace")
        state["quality_gate"] = {
            "status": "failed",
            "stdout": str(stdout_dest),
            "command": command,
            "exit_code": exit_code,
            "recorded_at": now(),
        }
        increment_quality_failure_round(state)
        add_blocker(state, f"quality gate process exited {exit_code}")
        write_state(root, state)
        print("Quality gate failed")
        return 1
    if not summary.exists():
        raise SystemExit(f"Quality summary does not exist: {summary}")
    decision = parse_quality_decision(summary)
    gate_results = validate_quality_results(results, required_gates, require_passed=True)
    required_gates_passed, deferred_human_review = quality_decision_allows_progress(decision, gate_results, required_gates)
    dest = root / "quality-gate-summary.md"
    copy_report(summary, dest)
    results_dest = root / "quality-gate-results.json"
    copy_report(results, results_dest)
    stdout_dest = root / "quality-gate-stdout.log"
    stdout_dest.write_text(stdout, encoding="utf-8", errors="replace")
    fingerprints = evidence_fingerprint(root, workspace)
    status = "passed" if required_gates_passed else "failed"
    state["quality_gate"] = {
        "summary": str(dest),
        "results": str(results_dest),
        "stdout": str(stdout_dest),
        "command": command,
        "exit_code": exit_code,
        "decision": decision,
        "status": status,
        "quality_profile": profile_name,
        "required_gates": required_gates,
        "deferred_human_review": deferred_human_review,
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "summary_fingerprint": sha256_bytes(dest.read_bytes()),
        "recorded_at": now(),
    }
    if status != "passed":
        increment_quality_failure_round(state)
        add_blocker(state, f"quality gate decision was {decision}")
        write_state(root, state)
        print("Quality gate failed")
        return 1
    write_state(root, state)
    print("Quality gate passed")
    return 0


def resolve_quality_gate_script(config: dict) -> Path:
    """Same trust ladder as the test gate: home-anchored config override,
    the ai-code-quality-gate companion skill, then the bundled fallback."""
    override = (config.get("quality_gate_script") or "").strip() if config.get("home_anchored") else ""
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend([default_quality_gate_script(), BUNDLED_QUALITY_GATE_SCRIPT])
    for item in candidates:
        if item.exists():
            return item
    raise SystemExit(
        "No quality gate script found. Install the ai-code-quality-gate skill, set quality_gate_script in the "
        "codex-dev-loop config, or restore the bundled scripts/quality_gate_fallback.py."
    )


def cmd_run_quality(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"quality_gate"})
    assert_phase_prereqs(root, state, "quality_gate", workspace)
    if not run_quality_budget_hook(root, workspace, state):
        write_state(root, state)
        return 1
    if not run_scope_check_hook(root, workspace, state, "before quality/commit"):
        write_state(root, state)
        return 1
    script = resolve_quality_gate_script(loop_config(state))
    profile_name = loop_config(state)["quality_profile"]
    profile = quality_profile(state)
    profile_gates = list(profile["quality_gates"])
    extra_required_gates = split_csv(args.require)
    required_gates = merge_unique(profile_gates, extra_required_gates)
    out_dir = Path(args.out_dir) if args.out_dir else workspace / ".codex" / "quality-gate" / dt.datetime.now().strftime("%Y%m%d-%H%M%S-dev-loop")
    if out_dir.exists():
        raise SystemExit(f"Quality gate out-dir already exists; refusing to reuse stale artifacts: {out_dir}")
    alignment_report = Path(args.alignment_report)
    if not alignment_report.is_absolute():
        alignment_report = workspace / alignment_report
    command = [
        sys.executable,
        str(script),
        "--workspace",
        str(workspace),
        "--out-dir",
        str(out_dir),
        "--alignment-report",
        str(alignment_report),
        "--timeout",
        str(args.timeout),
    ]
    if profile.get("strict"):
        command.append("--strict")
    if required_gates:
        command.extend(["--require", ",".join(required_gates)])
    if args.pr_url:
        command.extend(["--pr-url", args.pr_url])
    for item in args.command:
        command.extend(["--command", item])
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    summary = out_dir / "summary.md"
    results = out_dir / "results.json"
    return record_quality_result(root, workspace, state, summary, results, command, result.returncode, result.stdout, required_gates, profile_name)


def cmd_record_branch(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"branch"})
    assert_phase_prereqs(root, state, "branch", workspace)
    if not is_git_repo(workspace):
        raise SystemExit("Cannot record a branch outside a git repository.")
    current_branch = current_git_branch(workspace)
    if current_branch != args.branch:
        raise SystemExit(f"Current git branch {current_branch!r} does not match requested branch {args.branch!r}.")
    if current_branch in PROTECTED_BRANCHES or current_branch.startswith("release/"):
        raise SystemExit(f"Refusing to use protected branch for dev loop: {current_branch}")
    state.setdefault("git", {})["branch"] = args.branch
    state["git"]["base_commit"] = current_git_head(workspace)
    state["git"]["branch_recorded_at"] = now()
    write_state(root, state)
    print(f"Recorded branch: {args.branch}")
    return 0


def cmd_record_commit(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"quality_gate", "pr"})
    assert_phase_prereqs(root, state, "quality_gate", workspace)
    if not quality_is_current(state, root, workspace):
        raise SystemExit("Cannot record a commit before quality gate passes.")
    if not run_scope_check_hook(root, workspace, state, "before commit"):
        write_state(root, state)
        return 1
    if not is_git_repo(workspace):
        raise SystemExit("Cannot record a commit outside a git repository.")
    current_branch = current_git_branch(workspace)
    recorded_branch = state.get("git", {}).get("branch")
    if recorded_branch and current_branch != recorded_branch:
        raise SystemExit(f"Current branch {current_branch!r} does not match recorded branch {recorded_branch!r}.")
    if current_branch in PROTECTED_BRANCHES or current_branch.startswith("release/"):
        raise SystemExit(f"Refusing to record a commit on protected branch: {current_branch}")
    current_head = current_git_head(workspace)
    if args.commit and args.commit != current_head:
        raise SystemExit(f"Current HEAD {current_head!r} does not match requested commit {args.commit!r}.")
    fingerprints = evidence_fingerprint(root, workspace)
    state["git"] = {
        **state.get("git", {}),
        "branch": recorded_branch or current_branch,
        "commit": current_head,
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "commit_recorded_at": now(),
    }
    write_state(root, state)
    print(f"Recorded commit: {current_head}")
    return 0


def cmd_record_pr(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"pr"})
    assert_phase_prereqs(root, state, "pr", workspace)
    if not is_git_repo(workspace):
        raise SystemExit("Cannot record a PR outside a git repository.")
    current_branch = current_git_branch(workspace)
    current_head = current_git_head(workspace)
    recorded_branch = state.get("git", {}).get("branch")
    if recorded_branch and recorded_branch != args.branch:
        raise SystemExit(f"PR branch {args.branch!r} does not match recorded branch {recorded_branch!r}")
    if current_branch != args.branch:
        raise SystemExit(f"Current branch {current_branch!r} does not match PR branch {args.branch!r}.")
    if current_head != args.commit:
        raise SystemExit(f"Current HEAD {current_head!r} does not match PR commit {args.commit!r}.")
    if "github.com/" not in args.pr_url or "/pull/" not in args.pr_url:
        raise SystemExit("PR URL must be a GitHub pull request URL.")
    expected_repo = git_origin_repository(workspace)
    if args.allow_local_simulation:
        assert_test_mode("PR local simulation")
        if not args.evidence:
            raise SystemExit("--evidence is required with --allow-local-simulation.")
        pr_data = validate_pr_evidence(load_json_file(Path(args.evidence)), args.branch, args.commit, args.pr_url, expected_repo)
    else:
        pr_data = validate_pr_evidence(
            run_gh_json(workspace, args.gh, ["pr", "view", args.pr_url, "--json", "url,headRefName,headRefOid,state,baseRepository"]),
            args.branch,
            args.commit,
            args.pr_url,
            expected_repo,
        )
    evidence_dest = root / "pr-evidence.json"
    evidence_dest.write_text(json.dumps(pr_data, indent=2), encoding="utf-8")
    fingerprints = evidence_fingerprint(root, workspace)
    state["git"] = {
        **state.get("git", {}),
        "branch": args.branch,
        "commit": args.commit,
        "pr_url": args.pr_url,
        "pr_evidence": str(evidence_dest),
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "recorded_at": now(),
    }
    write_state(root, state)
    print(f"Recorded PR: {args.pr_url}")
    return 0


def cmd_record_cloud(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"cloud_checks"})
    assert_phase_prereqs(root, state, "cloud_checks", workspace)
    profile = quality_profile(state)
    required_checks = [*profile["cloud_checks"], *args.extra_required_check]
    if args.allow_local_simulation:
        assert_test_mode("GitHub Actions local simulation")
        if not args.evidence:
            raise SystemExit("--evidence is required with --allow-local-simulation.")
        cloud_data = load_json_file(Path(args.evidence))
    else:
        pr_url = state.get("git", {}).get("pr_url")
        if not pr_url:
            raise SystemExit("Missing recorded PR URL for GitHub Actions checks.")
        cloud_data = run_gh_json(workspace, args.gh, ["pr", "checks", pr_url, "--json", "name,state,link"])
    checks = validate_cloud_evidence(cloud_data, required_checks, require_ai_review=bool(profile["require_ai_review"])) if args.status == "passed" else []
    evidence_dest = root / "github-actions-evidence.json"
    evidence_dest.write_text(json.dumps(cloud_data, indent=2), encoding="utf-8")
    fingerprints = evidence_fingerprint(root, workspace)
    state["github_actions"] = {
        "status": args.status,
        "evidence": str(evidence_dest),
        "checks": checks,
        "required_checks": required_checks,
        "quality_profile": loop_config(state)["quality_profile"],
        "require_ai_review": bool(profile["require_ai_review"]),
        "plan_fingerprint": fingerprints["plan"],
        "workspace_fingerprint": fingerprints["workspace"],
        "recorded_at": now(),
    }
    if args.status != "passed":
        add_blocker(state, "GitHub Actions cloud checks failed or are blocked")
        write_state(root, state)
        print("GitHub Actions cloud checks blocked")
        return 1
    write_state(root, state)
    print("GitHub Actions cloud checks passed")
    return 0


def cmd_record_spec_merge(args: argparse.Namespace) -> int:
    """Verify that the reviewed spec-delta.md is reflected in the repository
    spec baseline and record it with evidence fingerprints.

    The agent performs the actual merge edit in <spec_dir>/<capability>.md;
    this command checks the result mechanically: every ADDED/MODIFIED
    '#### Requirement:' title must exist in the capability file and every
    REMOVED title must be gone. The record binds to plan and workspace
    fingerprints, so later code or spec edits invalidate it and the phase
    gates force a re-check. Because the baseline lives inside the workspace,
    spec updates ride the same branch, diff, reviews, and PR as the code."""
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    if not run_scope_check_hook(root, workspace, state, "before spec merge"):
        write_state(root, state)
        return 1
    if not run_budget_check_hook(root, workspace, state, "before spec merge"):
        write_state(root, state)
        return 1
    delta = load_spec_delta(root)
    config = loop_config(state)
    spec_dir = workspace / config["spec_dir"]
    if delta["no_impact_reason"]:
        record = {
            "status": "no-impact",
            "reason": delta["no_impact_reason"],
            "spec_dir": config["spec_dir"],
            **{f"{key}_fingerprint": value for key, value in evidence_fingerprint(root, workspace).items()},
            "recorded_at": now(),
        }
        state["spec_merge"] = record
        write_state(root, state)
        print("Spec merge recorded: no spec impact (reason kept in spec-delta.md).")
        return 0
    problems, merged = spec_delta_baseline_problems(delta, spec_dir)
    if problems:
        raise SystemExit("Spec baseline does not match spec-delta.md:\n- " + "\n- ".join(problems))
    record = {
        "status": "merged",
        "spec_dir": config["spec_dir"],
        "capabilities": merged,
        **{f"{key}_fingerprint": value for key, value in evidence_fingerprint(root, workspace).items()},
        "recorded_at": now(),
    }
    state["spec_merge"] = record
    write_state(root, state)
    total = sum(len(buckets["added"]) + len(buckets["modified"]) + len(buckets["removed"]) for buckets in merged.values())
    print(f"Spec merge recorded: {total} requirement change(s) across {len(merged)} capability file(s) in {config['spec_dir']}/.")
    return 0


def slug_for_archive(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "-" for char in value.strip())
    cleaned = cleaned.strip("-.")
    return cleaned or "run"


def cmd_archive(args: argparse.Namespace) -> int:
    """Move the finished run's records out of the working root so the next
    init starts clean and past runs stay browsable next to the spec baseline."""
    root = Path(args.root)
    state = read_state(root)
    assert_phase(state, {"complete"})
    branch = state.get("git", {}).get("branch", "")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_base = root.parent / f"{root.name}-archive"
    dest = archive_base / f"{stamp}-{slug_for_archive(branch)}"
    if dest.exists():
        raise SystemExit(f"Archive destination already exists: {dest}")
    archive_base.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root), str(dest))
    print(f"Archived dev loop records to {dest}")
    return 0


def cmd_set_scale(args: argparse.Namespace) -> int:
    root = Path(args.root)
    state = read_state(root)
    target = args.scale
    if target not in SCALE_INDEX:
        raise SystemExit(f"Unknown scale: {target!r}; use one of: {', '.join(SCALES)}.")
    current = loop_scale(state)
    if target == current:
        print(f"Scale already {current}.")
        return 0
    current_phase = phase(state)
    if SCALE_INDEX[target] < SCALE_INDEX[current] and current_phase not in {"intake", "planning"}:
        raise SystemExit(
            f"Cannot lower scale from {current} to {target} in phase {current_phase}; "
            "lowering is only allowed during intake or planning. Raising scale is allowed anytime."
        )
    state["scale"] = target
    history = state.setdefault("scale_history", [])
    history.append({"from": current, "to": target, "phase": current_phase, "at": now()})
    write_state(root, state)
    print(f"Scale set to {target} (was {current}).")
    if SCALE_INDEX[target] > SCALE_INDEX[current]:
        print("Heavier gates now apply; redo any phase gate the new scale requires (for example risk review).")
    return 0


def cmd_resolve_blocker(args: argparse.Namespace) -> int:
    """Clear recorded blockers so the loop can recover without hand-editing state.

    Every phase transition asserts there are no blockers, so without this
    command a blocked loop could never legally backtrack. Resolution requires
    a written reason, is appended to blocker-resolutions.md, and is kept as an
    auditable record in loop state. The log is intentionally a separate file:
    decision-log.md participates in the plan fingerprint, so appending there
    would invalidate every recorded review as a side effect.
    """
    root = Path(args.root)
    state = read_state(root)
    blockers = state.get("blockers") or []
    if not blockers:
        print("No blockers to resolve.")
        return 0
    reason = args.reason.strip()
    if len(reason) < 10:
        raise SystemExit("--reason must describe how the blocker was addressed (at least 10 characters).")
    resolved_at = now()
    resolutions = state.setdefault("blocker_resolutions", [])
    resolutions.append({"blockers": list(blockers), "reason": reason, "resolved_at": resolved_at})
    state["blockers"] = []
    state["failure_counter_reset_at"] = resolved_at
    resolution_log = root / "blocker-resolutions.md"
    if not resolution_log.exists():
        resolution_log.write_text("# Blocker Resolutions\n", encoding="utf-8")
    entry_lines = [f"\n## Blocker Resolution ({resolved_at})\n\n"]
    entry_lines.extend(f"- Resolved: {item}\n" for item in blockers)
    entry_lines.append(f"- Reason: {reason}\n")
    with resolution_log.open("a", encoding="utf-8") as handle:
        handle.write("".join(entry_lines))
    write_state(root, state)
    print(f"Resolved {len(blockers)} blocker(s); reason recorded in blocker-resolutions.md.")
    print("Backtrack with set-phase to redo the invalidated work before advancing again.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    automation_level = loop_config(state)["automation_level"]
    findings: list[str] = []
    try:
        assert_core_artifacts(root, loop_scale(state))
    except SystemExit as exc:
        findings.append(str(exc))
    if args.require_reviews:
        roles = required_review_roles(state, automation_level)
        for role in roles:
            if not review_is_current(state, role, root, workspace):
                findings.append(f"Missing current passing review: {role}")
    if args.require_final:
        final_records = ["final-report.md"]
        if automation_level != "planning_only":
            final_records.extend(["quality-gate-summary.md", "quality-gate-results.json"])
        if automation_level == "pr_without_merge":
            final_records.extend(["pr-body.md", "github-actions.md"])
        for name in final_records:
            if not (root / name).exists():
                findings.append(f"Missing final record: {name}")
        git = state.get("git", {})
        if automation_level != "planning_only" and not git.get("commit"):
            findings.append("Missing commit hash")
        if automation_level == "pr_without_merge" and not git.get("pr_url"):
            findings.append("Missing PR URL")
        if automation_level != "planning_only" and not quality_is_current(state, root, workspace):
            findings.append("Quality gate is not recorded as current and passed")
        if automation_level == "commit_only" and not git_commit_is_current(state, root, workspace):
            findings.append("Commit record is not current")
        if automation_level == "pr_without_merge" and not git_pr_is_current(state, root, workspace):
            findings.append("PR record is not current")
        if automation_level == "pr_without_merge" and not cloud_is_current(state, root, workspace):
            findings.append("GitHub Actions cloud checks are not recorded as current and passed")
    if state.get("blockers"):
        findings.extend(f"Blocker: {item}" for item in state["blockers"])
    if findings:
        print("Dev loop harness validation failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Dev loop harness state is valid.")
    return 0
