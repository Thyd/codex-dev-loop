"""Issue-scoped retry accounting derived from recorded test evidence."""

from __future__ import annotations


def normalize_issue(issue: str | None) -> str | None:
    if issue is None:
        return None
    value = issue.strip()
    if not value or not value.isprintable():
        raise SystemExit("--issue must be a non-empty, single-line printable identifier.")
    return value


def issue_key(unit: str, issue: str | None) -> str:
    # Separate namespaces prevent an explicit ID from aliasing a unit fallback.
    return f"issue:{issue}" if issue is not None else f"unit:{unit}"


def next_attempt_sequence(state: dict) -> int:
    # Keep this ordering clock when evidence is invalidated during backtracking.
    # A timestamp alone cannot order passes and failures from different units.
    sequence = max(
        [state.get("test_attempt_sequence", 0)]
        + [record.get("attempt_sequence", 0)
           for attempts in state.get("test_attempts", {}).values() for record in attempts]
    ) + 1
    state["test_attempt_sequence"] = sequence
    return sequence


def issue_attempts(state: dict, unit: str, issue: str | None) -> list[dict]:
    key = issue_key(unit, issue)
    records = [
        record
        for recorded_unit, attempts in state.get("test_attempts", {}).items()
        for record in attempts
        if issue_key(recorded_unit, record.get("issue_id")) == key
    ]
    # Unit fallbacks already have an append-ordered list, including evidence
    # adopted from standalone commands that does not carry a loop sequence.
    if issue is None:
        return records
    return sorted(records, key=lambda record: record.get("attempt_sequence", 0))


def issue_failure_count(state: dict, unit: str, issue: str | None) -> int:
    reset_sequence = state.get("test_failure_resets", {}).get(issue_key(unit, issue))
    legacy_reset = state.get("failure_counter_reset_at", "")
    count = 0
    for record in reversed(issue_attempts(state, unit, issue)):
        if (record.get("stage") or "green") == "red":
            continue
        if reset_sequence is not None and record.get("attempt_sequence", 0) <= reset_sequence:
            break
        if "attempt_sequence" not in record and legacy_reset and record.get("recorded_at", "") <= legacy_reset:
            break
        if record.get("status") == "passed":
            break
        count += 1
    return count


def reset_exhausted_issues(state: dict, retry_limit: int) -> list[str]:
    scopes = {
        issue_key(unit, record.get("issue_id")): (unit, record.get("issue_id"))
        for unit, attempts in state.get("test_attempts", {}).items() for record in attempts
    }
    exhausted = [key for key, (unit, issue) in scopes.items()
                 if issue_failure_count(state, unit, issue) > retry_limit]
    if exhausted:
        # Reserve a sequence boundary; future attempts advance beyond it even
        # after clear_downstream_state discards the old attempt lists.
        boundary = next_attempt_sequence(state)
        resets = state.setdefault("test_failure_resets", {})
        for key in exhausted:
            resets[key] = boundary
    return exhausted
