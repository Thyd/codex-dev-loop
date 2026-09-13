"""Verified GitHub quota failures and locally executed replacement checks."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import signal
import subprocess
import uuid

from .settings import loop_config, now
from .validation import (
    is_ai_review_check, matching_required_checks, passing_check,
    validate_cloud_evidence, validate_pr_evidence,
)
from .workspace import (
    add_blocker, current_git_head, evidence_fingerprint, git_origin_repository,
    sha256_bytes, write_state,
)


def quota_message(text: str) -> bool:
    """Recognize explicit service quota diagnostics, not a generic failed job."""
    value = " ".join(text.lower().split())
    return any(phrase in value for phrase in (
        "job was not started because recent account payments have failed",
        "job was not started because your spending limit",
        "you have exceeded your spending limit",
        "you have used up your included minutes",
        "you have exhausted your included minutes",
    ))


def paginated_items(data: object, key: str | None = None) -> list[dict]:
    if not isinstance(data, list):
        raise SystemExit("Expected paginated GitHub API evidence.")
    items = []
    for page in data:
        values = page.get(key) if key and isinstance(page, dict) else page
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise SystemExit("Malformed paginated GitHub API evidence.")
        items.extend(values)
    return items


def verify_current_pr(state: dict, workspace: Path, fetch: Callable) -> dict:
    git = state["git"]
    if current_git_head(workspace) != git["commit"]:
        raise SystemExit("Recorded PR commit no longer matches local HEAD.")
    return validate_pr_evidence(
        fetch(["pr", "view", git["pr_url"], "--json", "url,headRefName,headRefOid,state,baseRepository"]),
        git["branch"], git["commit"], git["pr_url"], git_origin_repository(workspace),
    )


def verify_quota_failures(state: dict, workspace: Path, checks: object,
                          required: list[str], require_ai_review: bool, fetch: Callable) -> dict:
    pr = verify_current_pr(state, workspace, fetch)
    if not isinstance(checks, list) or any(not isinstance(item, dict) for item in checks):
        raise SystemExit("GitHub Actions evidence must be a list of checks.")
    # Validate presence and names using the usual profile rules, then examine
    # the actual outcomes below. This copy is never persisted as passing CI.
    validate_cloud_evidence(
        [{**item, "state": "success", "conclusion": "success"} for item in checks],
        required, require_ai_review=require_ai_review,
    )
    needed = [item for item in checks if any(item in matching_required_checks(checks, name) for name in required)
              or is_ai_review_check(item["name"])]
    failed = [item for item in needed if not passing_check(item)]
    if not failed:
        raise SystemExit("No required quota-blocked checks; use record-cloud --status passed.")
    repo = git_origin_repository(workspace)
    head = state["git"]["commit"]
    runs = paginated_items(fetch(["api", f"repos/{repo}/commits/{head}/check-runs", "--paginate", "--slurp"]), "check_runs")
    blocked = []
    for check in failed:
        matches = [run for run in runs if run.get("name") == check["name"]
                   and check.get("link") and check["link"] in {run.get("html_url"), run.get("details_url")}
                   and run.get("head_sha") == head
                   and (run.get("app") or {}).get("slug") == "github-actions"
                   and run.get("status") == "completed" and run.get("conclusion") == "failure"]
        if len(matches) != 1:
            raise SystemExit(f"Cannot verify a current GitHub Actions quota failure for {check['name']!r}.")
        run = matches[0]
        annotations = paginated_items(fetch(["api", f"repos/{repo}/check-runs/{run['id']}/annotations", "--paginate", "--slurp"]))
        output = run.get("output") or {}
        diagnostics = [str(output.get(key) or "") for key in ("title", "summary", "text")]
        diagnostics.extend(str(item.get("message") or "") for item in annotations)
        if not any(quota_message(message) for message in diagnostics):
            raise SystemExit(f"{check['name']!r} has no explicit GitHub quota/billing diagnostic; do not downgrade code or setup failures.")
        blocked.append({"name": check["name"], "check_run": run, "annotations": annotations})
    return {"pr": pr, "commit": head, "checks": checks, "blocked_checks": blocked}


def local_commands(values: list[str], blocked: list[str]) -> dict[str, str]:
    commands = {}
    for value in values:
        name, separator, command = value.partition("=")
        name, command = name.strip(), command.strip()
        if not separator or not name or not command or name in commands:
            raise SystemExit("Each --local-check must be a unique CHECK=COMMAND with a non-empty command.")
        if name not in blocked:
            raise SystemExit(f"Local check {name!r} does not name a verified quota-blocked check.")
        commands[name] = command
    return commands


def execute_local_check(command: str, workspace: Path, output, timeout: int) -> int:
    """Stop the entire test process tree on timeout or interrupted execution."""
    process = subprocess.Popen(
        command, shell=True, cwd=str(workspace), stdin=subprocess.DEVNULL,
        stdout=output, stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        return process.wait(timeout=timeout)
    except BaseException:
        if os.name == "nt":
            # Popen.kill() terminates only cmd.exe; taskkill /T includes its
            # test children. Run it before killing/reaping the parent.
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            finally:
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        raise


def record_quota_result(args, root: Path, workspace: Path, state: dict,
                        checks: object, required: list[str], require_ai_review: bool,
                        fetch: Callable) -> int:
    evidence = verify_quota_failures(state, workspace, checks, required, require_ai_review, fetch)
    fingerprints = evidence_fingerprint(root, workspace)
    attempt_dir = root.resolve() / "ci-quota" / uuid.uuid4().hex
    attempt_dir.mkdir(parents=True)
    path = attempt_dir / "github-quota.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    blocked = sorted({item["name"] for item in evidence["blocked_checks"]})
    policy = loop_config(state)["ci_quota_policy"]
    record = {
        "status": "waiting_for_payment" if policy == "wait_for_payment" else "local_fallback_required",
        "cloud_status": "quota-exhausted", "ci_quota_policy": policy,
        "commit": evidence["commit"], "pr_url": state["git"]["pr_url"],
        "evidence": path.relative_to(root.resolve()).as_posix(), "evidence_sha256": sha256_bytes(path.read_bytes()),
        "checks": checks, "required_checks": required, "quota_blocked_checks": blocked,
        "quality_profile": loop_config(state)["quality_profile"], "require_ai_review": require_ai_review,
        "plan_fingerprint": fingerprints["plan"], "workspace_fingerprint": fingerprints["workspace"],
        "recorded_at": now(), "local_checks": [],
    }
    state["github_actions"] = record

    def save(message: str, blocker: bool = False) -> int:
        if blocker:
            add_blocker(state, message)
        write_state(root, state)
        lines = ["# GitHub Actions\n", f"- PR: {record['pr_url']}", f"- Commit: {record['commit']}",
                 "- Cloud status: quota-exhausted", f"- Decision: {record['status']}",
                 f"- Policy: {policy}", f"- [GitHub evidence]({record['evidence']})", f"- Note: {message}", "\n## Local checks\n"]
        lines.extend(f"- {item['name']}: exit {item['exit_code']}; command `{item['command']}`; [log]({item['log']})"
                     for item in record["local_checks"])
        (root / "github-actions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(message)
        return 0 if record["status"] == "local_fallback_passed" else 1

    if policy == "wait_for_payment":
        return save("CI quota exhausted. Wait for user payment/quota restoration, rerun GitHub CI, then resolve-blocker and record-cloud --status passed.", blocker=True)
    commands = local_commands(args.local_check, blocked)
    missing = [name for name in blocked if name not in commands]
    if missing:
        record["pending_local_checks"] = missing
        return save("Current agent must supply equivalent --local-check CHECK=COMMAND for: " + ", ".join(missing))
    if args.timeout <= 0:
        raise SystemExit("Local check timeout must be positive.")
    # Write the pending state before running a command so interruption cannot
    # retain a previous passing record.
    write_state(root, state)
    for index, (name, command) in enumerate(commands.items(), start=1):
        log = attempt_dir / f"local-{index}.log"
        started_at = now()
        try:
            with log.open("w", encoding="utf-8") as output:
                exit_code = execute_local_check(command, workspace, output, args.timeout)
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            exit_code = -1
            with log.open("a", encoding="utf-8") as output:
                output.write(f"\nLocal check could not complete: {exc}\n")
        record["local_checks"].append({"name": name, "command": command, "exit_code": exit_code,
                                       "log": log.relative_to(root.resolve()).as_posix(), "log_sha256": sha256_bytes(log.read_bytes()),
                                       "started_at": started_at, "finished_at": now()})
        if exit_code != 0:
            record["status"] = "local_fallback_failed"
            return save(f"Local replacement check failed: {name}. Fix the failure before continuing.", blocker=True)
    if evidence_fingerprint(root, workspace) != fingerprints or current_git_head(workspace) != record["commit"]:
        record["status"] = "local_fallback_failed"
        return save("Workspace, plan, or HEAD changed during local checks; redo affected evidence before continuing.", blocker=True)
    verify_current_pr(state, workspace, fetch)
    record["status"] = "local_fallback_passed"
    return save("Local replacement checks passed; GitHub CI remains quota-blocked. Continue at the configured automation level; disclose this result in the PR and final report.")


def local_quota_evidence_is_valid(record: dict, state: dict, root: Path, workspace: Path) -> bool:
    if loop_config(state)["ci_quota_policy"] != "local_fallback" or record.get("ci_quota_policy") != "local_fallback":
        return False
    if record.get("commit") != current_git_head(workspace) or record.get("pr_url") != state.get("git", {}).get("pr_url"):
        return False
    results = record.get("local_checks") or []
    blocked = record.get("quota_blocked_checks") or []
    if not blocked or {item.get("name") for item in results} != set(blocked):
        return False
    if any(item.get("exit_code") != 0 for item in results):
        return False
    try:
        if sha256_bytes((root / record["evidence"]).read_bytes()) != record["evidence_sha256"]:
            return False
        return all(sha256_bytes((root / item["log"]).read_bytes()) == item["log_sha256"] for item in results)
    except (OSError, KeyError, TypeError):
        return False
