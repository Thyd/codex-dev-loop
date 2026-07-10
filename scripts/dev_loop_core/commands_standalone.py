"""Diagnostics and composable standalone command handlers."""

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
    ACCEPTANCE_HEADINGS,
    CANONICAL_LOOP_DIR,
    CONFIG_SCHEMA_VERSION,
    DEFAULT_EVIDENCE_DIRNAME,
    GOAL_HEADINGS,
    HOME_ENV,
    PROTECTED_BRANCHES,
    REVIEW_SECTIONS,
    STANDALONE_REVIEW_ROLES,
    TDD_MODES,
    TEST_STAGES,
    default_config,
    default_config_path,
    load_loop_config,
    loop_config,
    now,
    split_csv,
)
from .workspace import (
    add_blocker,
    assert_no_blockers,
    current_git_branch,
    is_git_repo,
    parse_key_value_output,
    parse_report_field,
    phase,
    plan_fingerprint,
    planned_units,
    print_scope_check,
    read_state,
    red_validation_allows_evidence,
    review_decision_allows_progress,
    run_child,
    scope_check_result,
    sensitive_changed_paths,
    unit_tdd_mode,
    valid_review_decisions,
    workspace_fingerprint,
    write_state,
)
from .specs import (
    parse_spec_delta,
    spec_delta_baseline_problems,
    validate_delta_shape,
)
from .validation import (
    any_section_has_content,
    assert_phase,
    copy_report,
    load_test_meta,
    parse_decision,
    validate_agent_id,
    validate_red_failure,
)
from .commands_loop import (
    resolve_test_gate_script,
)

def collect_evidence_documents(
    root: Path,
    workspace: Path,
    config_path: str = "",
) -> tuple[list[dict], list[dict]]:
    """Load every known evidence document before doctoring or migration.

    The collection is deliberately two-phase: callers validate all documents
    first, then write. A bad future/corrupt document therefore cannot leave a
    partially migrated evidence set behind.
    """

    documents: list[dict] = []
    errors: list[dict] = []
    state: dict | None = None
    state_path = root / "loop-state.json"
    if state_path.exists():
        try:
            state, report = load_evidence_document(state_path, "loop-state")
            documents.append(
                {
                    "path": state_path,
                    "kind": "loop-state",
                    "data": state,
                    "report": report,
                }
            )
        except EvidenceContractError as exc:
            errors.append({"path": str(state_path), "kind": "loop-state", "error": str(exc)})

    try:
        config = loop_config(state) if state is not None else load_loop_config(config_path)
    except SystemExit as exc:
        errors.append({"path": config_path or str(default_config_path()), "kind": "config", "error": str(exc)})
        config = default_config()

    evidence_root = resolve_evidence_dir(workspace, config)
    for kind, path in (
        ("tdd", evidence_root / "tdd" / "ledger.json"),
        ("review", evidence_root / "review" / "ledger.json"),
    ):
        if not path.exists():
            continue
        try:
            data, report = load_evidence_document(path, kind)
            documents.append({"path": path, "kind": kind, "data": data, "report": report})
        except EvidenceContractError as exc:
            errors.append({"path": str(path), "kind": kind, "error": str(exc)})
    return documents, errors


def evidence_document_summary(item: dict, *, written: bool = False) -> dict:
    report = item["report"]
    return {
        "path": str(item["path"]),
        "kind": item["kind"],
        "from_version": report.from_version,
        "to_version": report.to_version,
        "needs_migration": report.changed,
        "changes": list(report.changes),
        "written": written,
    }


def print_evidence_status(payload: dict) -> None:
    print(
        f"codex-dev-loop evidence: {payload['status']} "
        f"(core {payload['core_version']}, schema {payload['evidence_schema_version']})"
    )
    for item in payload.get("documents", []):
        marker = "needs migration" if item["needs_migration"] else "current"
        if item.get("written"):
            marker = "migrated"
        print(f"- {item['kind']}: {marker}: {item['path']}")
    for error in payload.get("errors", []):
        print(f"- ERROR {error['kind']}: {error['path']}: {error['error']}")


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    documents, errors = collect_evidence_documents(root, workspace, args.config)
    needs_migration = any(item["report"].changed for item in documents)
    status = "error" if errors else "needs-migration" if needs_migration else "ok"
    payload = {
        "status": status,
        "core_version": CORE_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "documents": [evidence_document_summary(item) for item in documents],
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print_evidence_status(payload)
    return 0 if status == "ok" else 1


def cmd_migrate_evidence(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    documents, errors = collect_evidence_documents(root, workspace, args.config)
    summaries: list[dict] = []
    written_count = 0
    if not errors:
        for item in documents:
            written = False
            if item["report"].changed and not args.dry_run:
                try:
                    write_evidence_document(item["path"], item["data"], item["kind"])
                except EvidenceContractError as exc:
                    errors.append(
                        {"path": str(item["path"]), "kind": item["kind"], "error": str(exc)}
                    )
                    break
                written = True
                written_count += 1
            summaries.append(evidence_document_summary(item, written=written))

    needs_migration = any(item["report"].changed for item in documents)
    if errors:
        status = "error"
    elif written_count:
        status = "migrated"
    elif needs_migration:
        status = "needs-migration"
    else:
        status = "up-to-date"
    payload = {
        "status": status,
        "dry_run": bool(args.dry_run),
        "core_version": CORE_VERSION,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "documents": summaries,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print_evidence_status(payload)
    return 1 if errors else 0


def host_is_codex() -> bool:
    return not os.environ.get(HOME_ENV, "").strip()


def resolve_evidence_dir(workspace: Path, config: dict) -> Path:
    configured = (config.get("evidence_dir") or "").strip()
    if configured:
        return workspace / configured
    return workspace / DEFAULT_EVIDENCE_DIRNAME


def active_loop_state_path(workspace: Path) -> Path:
    return workspace / CANONICAL_LOOP_DIR / "loop-state.json"


def assert_no_active_loop(workspace: Path) -> None:
    path = active_loop_state_path(workspace)
    if not path.exists():
        return
    try:
        state, _report = load_evidence_document(path, "loop-state")
    except EvidenceContractError as exc:
        raise SystemExit(
            f"Cannot trust active loop state {path}; standalone writes are fail-closed: {exc}"
        ) from exc
    current = state.get("phase", "")
    if current and current != "complete":
        raise SystemExit(
            f"An active dev loop exists at {path.parent} (phase: {current}). "
            "Standalone skills are disabled while a loop runs so evidence cannot fork; "
            "use the loop's own commands, or finish and archive the loop first."
        )


def load_ledger(path: Path, kind: str) -> dict:
    if not path.exists():
        data, _report = normalize_evidence_document(
            {"attempts": {}, "reviews": []},
            kind,
        )
        return data
    try:
        data, _report = load_evidence_document(path, kind)
    except EvidenceContractError as exc:
        raise SystemExit(f"Cannot trust evidence ledger {path}: {exc}") from exc
    return data


def save_ledger(path: Path, data: dict) -> None:
    data["updated_at"] = now()
    kind = str(data.get("kind") or "")
    try:
        write_evidence_document(path, data, kind)
    except EvidenceContractError as exc:
        raise SystemExit(f"Cannot write evidence ledger {path}: {exc}") from exc


def hash_target_paths(workspace: Path, rel_paths: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in rel_paths:
        normalized = rel.replace("\\", "/")
        digest.update(normalized.encode("utf-8"))
        path = workspace / normalized
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def standalone_has_red(attempts: list[dict]) -> bool:
    return any(
        item.get("stage") == "red" and item.get("status") == "failed" and red_validation_allows_evidence(item)
        for item in attempts
    )


def cmd_version(args: argparse.Namespace) -> int:
    if args.require:
        installed = parse_version_tuple(CORE_VERSION)
        required = parse_version_tuple(args.require)
        if installed < required:
            raise SystemExit(f"Installed core {CORE_VERSION} is older than required {args.require}.")
    if args.json:
        print(
            json.dumps(
                {
                    "core_version": CORE_VERSION,
                    "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                    "config_schema_version": CONFIG_SCHEMA_VERSION,
                },
                sort_keys=True,
            )
        )
    else:
        print(f"codex-dev-loop-core {CORE_VERSION}")
    return 0


def parse_version_tuple(value: str) -> tuple:
    numbers = []
    for part in value.split("-", 1)[0].split("."):
        if part.isdigit():
            numbers.append(int(part))
        else:
            break
    return tuple(numbers)


def cmd_scope_check(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not is_git_repo(workspace):
        raise SystemExit("scope-check requires a git repository.")
    root = Path(args.root)
    state: dict | None = None
    state_path = root / "loop-state.json"
    if state_path.exists():
        state = read_state(root)
    plan = Path(args.plan) if args.plan else root / "development-plan.md"
    design = Path(args.design) if args.design else root / "technical-design.md"
    result = scope_check_result(root, workspace, state=state, plan_path=plan, design_path=design, base_ref=args.base_ref)
    print_scope_check(result)
    if state is not None:
        state["scope_check"] = {**result, "context": "manual scope-check", "recorded_at": now()}
        if result["status"] != "passed" and phase(state) != "complete":
            add_blocker(state, "scope-check failed: " + "; ".join(result["findings"]))
        write_state(root, state)
    return 0 if result["status"] == "passed" else 1


def cmd_guard_check(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not is_git_repo(workspace):
        raise SystemExit("guard-check requires a git repository.")
    sensitive = sensitive_changed_paths(workspace)
    if sensitive:
        print("Sensitive paths in the current change set (escalate beyond a micro/small chain):")
        for path in sorted(sensitive):
            print(f"- {path}")
        return 1
    print("No sensitive paths in the current change set.")
    return 0


def cmd_check_spec(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"Spec file does not exist: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not any_section_has_content(text, GOAL_HEADINGS) or not any_section_has_content(text, ACCEPTANCE_HEADINGS):
        raise SystemExit(
            f"{path} must contain non-empty '## Goal' and '## Acceptance Criteria' sections. "
            "Keep clarifying with the user (record Q&A in a clarification log) until both are concrete."
        )
    print(f"{path}: Goal and Acceptance Criteria are present and non-empty.")
    return 0


def cmd_validate_red(args: argparse.Namespace) -> int:
    validation = validate_red_failure(args.unit, Path(args.log), args.expected, status=args.status)
    print(f"RED_TEST_VALIDATION_STATUS={validation['status']}")
    print(f"RED_TEST_VALIDATION_REASON={validation['reason']}")
    if validation.get("expected"):
        print(f"RED_TEST_VALIDATION_EXPECTED={validation['expected']}")
    return 0 if validation["status"] == "pass" else 1


def cmd_standalone_fingerprint(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    targets = split_csv(args.target)
    if not targets:
        raise SystemExit("Pass --target as a comma-separated list of workspace-relative files.")
    print(f"TARGET_FINGERPRINT={hash_target_paths(workspace, targets)}")
    return 0


def cmd_standalone_test(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = load_loop_config(args.config)
    assert_no_active_loop(workspace)
    if is_git_repo(workspace):
        sensitive = sensitive_changed_paths(workspace)
        if sensitive:
            raise SystemExit(
                "Standalone TDD is not allowed after sensitive paths change; escalate to codex-dev-loop standard/large: "
                + ", ".join(sorted(sensitive))
            )
    if args.stage not in TEST_STAGES:
        raise SystemExit(f"Unknown test stage: {args.stage!r}; use red or green.")
    label = args.label.strip()
    if not label:
        raise SystemExit("Pass a non-empty --label to identify the behavior under test.")
    mode = args.mode
    if mode not in TDD_MODES:
        raise SystemExit(f"Unknown --mode {mode!r}; use red or regression-only.")
    ledger_path = resolve_evidence_dir(workspace, config) / "tdd" / "ledger.json"
    ledger = load_ledger(ledger_path, "tdd")
    attempts = ledger["attempts"].setdefault(label, [])
    # regression-only mirrors the loop's per-unit waiver: a change already
    # covered by existing tests (or a non-behavioral ship) records green
    # without a red run. Recorded honestly so the evidence shows which
    # discipline was used. The red stage is meaningless under this mode.
    if mode == "regression-only" and args.stage == "red":
        raise SystemExit("--mode regression-only has no red stage; run --stage green.")
    if mode == "red" and args.stage == "green" and not standalone_has_red(attempts):
        raise SystemExit(
            f"Green stage refused for {label!r}: no prior failing red run. "
            "Run --stage red against the new failing test first, or use --mode regression-only "
            "if existing tests already cover the change."
        )
    script = resolve_test_gate_script(config, args.test_gate_script)
    command = [
        sys.executable,
        str(script),
        "--unit",
        label,
        "--command",
        args.command,
        "--cwd",
        str(workspace),
        "--timeout",
        str(args.timeout),
    ]
    result = run_child(command, workspace)
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    meta_path = parse_key_value_output(result.stdout, "AUTODEV_TEST_META")
    if not meta_path:
        raise SystemExit("Test gate did not report AUTODEV_TEST_META.")
    meta = load_test_meta(Path(meta_path), label, workspace)
    record = {
        "stage": args.stage,
        "mode": mode,
        "status": meta["status"],
        "command": meta["command"],
        "exit_code": meta.get("exit_code"),
        "log": meta["log_path"],
        "meta": str(meta_path),
        "workspace_fingerprint": workspace_fingerprint(workspace),
        "recorded_at": now(),
    }
    if args.stage == "red":
        validation = validate_red_failure(label, Path(meta["log_path"]), args.expected_failure, status=meta["status"])
        record["red_validation"] = validation
        attempts.append(record)
        save_ledger(ledger_path, ledger)
        if meta["status"] == "passed":
            print(f"{label}: red-stage test PASSED before implementation; the test does not prove the missing behavior. Strengthen it.")
            return 1
        if meta["status"] != "failed":
            print(f"{label}: red-stage run ended with {meta['status']}; fix the test harness so the red run fails cleanly.")
            return 1
        if validation["status"] != "pass":
            print(f"{label}: red-stage failure rejected by red-test-validator ({validation['status']}): {validation['reason']}")
            return 1
        print(f"{label}: red evidence recorded ({ledger_path}; red-test-validator pass).")
        return 0
    attempts.append(record)
    save_ledger(ledger_path, ledger)
    if meta["status"] != "passed":
        print(f"{label}: green-stage run is {meta['status']}; keep iterating.")
        return 1
    print(f"{label}: green pass recorded ({ledger_path}).")
    return 0


def validate_standalone_review(role: str, report: Path, agent_id: str, target_fingerprint: str) -> None:
    text = report.read_text(encoding="utf-8", errors="replace")
    missing = [section for section in REVIEW_SECTIONS[role] if section.lower() not in text.lower()]
    if missing:
        raise SystemExit(f"{role} report is missing required sections: {', '.join(missing)}")
    if parse_report_field(text, "Agent ID:") != agent_id:
        raise SystemExit(f"{role} report Agent ID does not match --agent-id.")
    if parse_report_field(text, "Target Fingerprint:") != target_fingerprint:
        raise SystemExit(
            f"{role} report Target Fingerprint is stale or missing; it must echo the current TARGET_FINGERPRINT "
            "(get it from `standalone-fingerprint --target ...`)."
        )


def cmd_standalone_review(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = load_loop_config(args.config)
    assert_no_active_loop(workspace)
    role = args.role
    if role not in STANDALONE_REVIEW_ROLES:
        raise SystemExit(f"Unknown standalone review role: {role}; use one of: {', '.join(sorted(STANDALONE_REVIEW_ROLES))}")
    validate_agent_id(args.agent_id)
    targets = split_csv(args.target)
    if not targets:
        raise SystemExit("Pass --target as a comma-separated list of workspace-relative files under review.")
    src = Path(args.report)
    if not src.exists():
        raise SystemExit(f"Review report does not exist: {src}")
    decision = parse_decision(src)
    if decision not in valid_review_decisions(role):
        expected = ", ".join(sorted(valid_review_decisions(role)))
        raise SystemExit(f"Review report has invalid or missing Decision: {src}; expected one of: {expected}")
    target_fingerprint = hash_target_paths(workspace, targets)
    validate_standalone_review(role, src, args.agent_id, target_fingerprint)
    review_dir = resolve_evidence_dir(workspace, config) / "review"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = review_dir / f"{role}-{stamp}.md"
    copy_report(src, dest)
    ledger_path = review_dir / "ledger.json"
    ledger = load_ledger(ledger_path, "review")
    ledger["reviews"].append(
        {
            "role": role,
            "decision": decision,
            "targets": targets,
            "target_fingerprint": target_fingerprint,
            "agent_id": args.agent_id,
            "report": str(dest),
            "recorded_at": now(),
        }
    )
    save_ledger(ledger_path, ledger)
    print(f"{role}: {decision} (recorded to {ledger_path}).")
    return 0 if review_decision_allows_progress(role, decision) else 1


def cmd_check_spec_delta(args: argparse.Namespace) -> int:
    """Standalone spec-delta validation (dev-spec). Same mechanical check as the
    loop's record-spec-merge, but on a given delta file and spec dir, with no
    loop state. Used both after a merge edit and after bootstrap."""
    workspace = Path(args.workspace).resolve()
    delta_path = Path(args.delta)
    if not delta_path.exists():
        raise SystemExit(f"Spec delta file does not exist: {delta_path}")
    delta = validate_delta_shape(parse_spec_delta(delta_path.read_text(encoding="utf-8", errors="replace")))
    if delta["no_impact_reason"]:
        print("Spec delta declares no spec impact; nothing to reconcile against the baseline.")
        return 0
    spec_dir = workspace / args.spec_dir
    problems, merged = spec_delta_baseline_problems(delta, spec_dir)
    if problems:
        print("Spec baseline does not match the spec delta:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    total = sum(len(b["added"]) + len(b["modified"]) + len(b["removed"]) for b in merged.values())
    print(f"Spec baseline matches the delta: {total} requirement change(s) across {len(merged)} capability file(s) in {args.spec_dir}/.")
    return 0


def cmd_ship_check(args: argparse.Namespace) -> int:
    """Floor gate for dev-ship: a git repo, not on a protected branch, and a
    green test recorded against the exact tree being shipped. Standalone chains
    stay honest 鈥?you cannot open a PR without current green evidence."""
    workspace = Path(args.workspace).resolve()
    config = load_loop_config(args.config)
    assert_no_active_loop(workspace)
    if not is_git_repo(workspace):
        raise SystemExit("ship-check requires a git repository.")
    branch = current_git_branch(workspace)
    if not branch:
        raise SystemExit("ship-check requires a named branch (detached HEAD is not shippable).")
    if branch in PROTECTED_BRANCHES or branch.startswith("release/"):
        raise SystemExit(f"Refusing to ship from a protected branch: {branch}. Create a feature branch first.")
    sensitive = sensitive_changed_paths(workspace)
    if sensitive:
        raise SystemExit(
            "Refusing standalone shipping after sensitive paths changed; escalate to codex-dev-loop standard/large: "
            + ", ".join(sorted(sensitive))
        )
    labels = list(dict.fromkeys(label.strip() for label in args.label if label.strip()))
    if not labels:
        raise SystemExit("ship-check requires at least one --label identifying every behavior in this standalone change.")
    ledger_path = resolve_evidence_dir(workspace, config) / "tdd" / "ledger.json"
    if not ledger_path.exists():
        raise SystemExit(
            "No test evidence found. Record at least one green run with standalone-test "
            "(TDD or --mode regression-only) before shipping."
        )
    ledger = load_ledger(ledger_path, "tdd")
    current_workspace = workspace_fingerprint(workspace)
    problems: list[str] = []
    for label in labels:
        attempts = ledger.get("attempts", {}).get(label, [])
        if not attempts:
            problems.append(f"{label}: no evidence")
            continue
        latest = attempts[-1]
        if latest.get("stage") != "green" or latest.get("status") != "passed":
            problems.append(f"{label}: latest attempt is not a passing green")
        elif latest.get("workspace_fingerprint") != current_workspace:
            problems.append(f"{label}: green evidence is stale for the current tree")
    if problems:
        raise SystemExit("ship-check failed:\n- " + "\n- ".join(problems))
    print(f"ship-check passed on branch {branch}: {len(labels)} required label(s) are green for the shipping tree.")
    return 0


def cmd_adopt_evidence(args: argparse.Namespace) -> int:
    """Absorb standalone dev-tdd evidence into a running loop (the upgrade path).

    When a user starts with dev-tdd and later escalates to the full loop, this
    imports each standalone green that still matches the current tree so the
    unit's test gate does not have to be re-run. Adoption is fingerprint-gated:
    a standalone green is only adopted when its workspace fingerprint equals the
    loop's current workspace fingerprint (the tree has not changed since). For a
    red-mode unit the matching failing red attempt is imported too, re-stamped
    to the current plan fingerprint, so the red-before-green gate is satisfied
    honestly. Units without a current standalone green are left for a normal run.
    """
    root = Path(args.root)
    workspace = Path(args.workspace).resolve()
    state = read_state(root)
    assert_phase(state, {"implementation"})
    assert_no_blockers(state)
    config = loop_config(state)
    ledger_path = resolve_evidence_dir(workspace, config) / "tdd" / "ledger.json"
    if not ledger_path.exists():
        print(f"No standalone tdd evidence to adopt at {ledger_path}.")
        return 0
    ledger = load_ledger(ledger_path, "tdd")
    current_plan = plan_fingerprint(root)
    current_workspace = workspace_fingerprint(workspace)
    adopted: list[str] = []
    skipped: list[str] = []
    for unit in planned_units(root):
        attempts = ledger.get("attempts", {}).get(unit, [])
        green = None
        for item in attempts:
            if item.get("stage") == "green" and item.get("status") == "passed" and item.get("workspace_fingerprint") == current_workspace:
                green = item
        if green is None:
            skipped.append(unit)
            continue
        loop_attempts = state.setdefault("test_attempts", {}).setdefault(unit, [])
        if unit_tdd_mode(root, unit) == "red":
            red = next((item for item in attempts if item.get("stage") == "red" and item.get("status") == "failed"), None)
            if red is not None:
                loop_attempts.append(
                    {
                        "status": "failed",
                        "stage": "red",
                        "command": red.get("command", ""),
                        "exit_code": red.get("exit_code"),
                        "log": red.get("log", ""),
                        "meta": red.get("meta", ""),
                        "plan_fingerprint": current_plan,
                        "workspace_fingerprint": current_workspace,
                        "recorded_at": now(),
                        "red_validation": red.get("red_validation", {"status": "pass", "reason": "adopted legacy standalone red evidence."}),
                        "adopted_from": "standalone",
                    }
                )
        loop_attempts.append(
            {
                "status": "passed",
                "stage": "green",
                "command": green.get("command", ""),
                "exit_code": green.get("exit_code"),
                "log": green.get("log", ""),
                "meta": green.get("meta", ""),
                "plan_fingerprint": current_plan,
                "workspace_fingerprint": current_workspace,
                "recorded_at": now(),
                "adopted_from": "standalone",
            }
        )
        adopted.append(unit)
    write_state(root, state)
    print(f"Adopted standalone green evidence for {len(adopted)} unit(s): {', '.join(adopted) or 'none'}.")
    if skipped:
        print(f"No current standalone green for {len(skipped)} unit(s) (run their gate normally): {', '.join(skipped)}.")
    return 0
