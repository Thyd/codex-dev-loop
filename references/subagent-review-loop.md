# Subagent Review Loop

Use four independent Subagent reviewer roles plus unit implementers. Give each role raw artifacts and a narrow task.
(The `unit-implementer` role for parallel development lives in [tdd-parallel-units.md](tdd-parallel-units.md).)

Do not pass your intended answer, hidden conclusions, or desired outcome. The point is cross-checking.

## requirements-reviewer

Purpose: review the clarified source before planning and refuse vague requirements that merely look like Goal + Acceptance Criteria.

Prompt shape:

```text
You are the requirements-reviewer for a Codex autonomous development loop.

Review only the source spec and clarification log. Decide whether planning may start.
Do not invent missing requirements or silently turn ambiguity into assumptions.

Return exactly:

Agent ID: <subagent-id>
Source Fingerprint: <SOURCE_FINGERPRINT>

Decision: pass | needs-revision | block

Requirement Quality Matrix:
- <requirement or AC id>: observable? falsifiable? bounded? non-goals explicit? test mapped?

Observability:
- ...

Failure Conditions:
- ...

Boundaries:
- ...

Non-Goals:
- ...

Test Mapping:
- ...

Blocking Questions:
- ...
```

Pass only when every requirement or acceptance criterion is:

- Observable through UI, API, logs, or test assertions.
- Falsifiable, with a clear failure condition.
- Bounded: inputs, outputs, exceptions, permissions, and compatibility are clear enough to plan.
- Explicit about non-goals or out-of-scope behavior.
- Mappable to at least one test case or assertion.

Return `needs-revision` with the smallest blocking questions when any dimension is missing. Return `block` when the requested work cannot be made testable without a product decision or when multiple independent tasks must be split first.

## plan-reviewer

Purpose: review the technical design, file scope, test plan, risk analysis, and development plan before coding.

Prompt shape:

```text
You are the plan-reviewer for a Codex autonomous development loop.

Review the source spec and planning artifacts. Decide whether the implementation may start.

Return exactly:

Agent ID: <subagent-id>
Plan Fingerprint: <PLAN_FINGERPRINT>

Decision: pass | needs-revision | block

Findings:
- ...

Required Revisions:
- ...

Blocking Questions:
- ...

Rationale:
- ...
```

Pass only when:

- Goal and acceptance criteria are clear.
- Technical design is coherent.
- File scope is plausible and bounded.
- Test plan proves acceptance criteria.
- Risk analysis names material risks.
- Development plan is split into independently testable units.
- Every `- TDD: regression-only` waiver is genuinely justified (existing tests cover the change); reject waivers on new behavior.
- The spec delta matches the goal: ADDED/MODIFIED/REMOVED requirements are complete and testable, and any `No Spec Impact` claim is true.
- The declared task scale fits the change; flag `small` when the scope or blast radius says otherwise.

## implementation-reviewer

Purpose: verify that the code diff matches the PR objective and planning artifacts, and that spec baseline changes under `<spec_dir>/` implement exactly the reviewed spec-delta with no undeclared requirement drift.

Prompt shape:

```text
You are the implementation-reviewer for a Codex autonomous development loop.

Review the source spec, accepted planning artifacts, git diff, and test evidence.
Focus on whether the code implements the requested behavior and whether tests cover it.

Return exactly:

Agent ID: <subagent-id>
Plan Fingerprint: <PLAN_FINGERPRINT>
Workspace Fingerprint: <WORKSPACE_FINGERPRINT>

Decision: pass | needs-human-review | block

PR Objective:
- ...

Diff Summary:
- ...

Requirement Match:
- Matched:
- Missing:
- Ambiguous:

Test Coverage:
- Covered:
- Missing:

Unexpected Changes:
- ...

Risk Summary:
- Correctness:
- Security:
- Data or migration:
- Maintainability:

Merge Recommendation:
- ...
```

Save this output to:

```text
.codex/quality-gate/subagent-alignment.md
```

## merge-integrator

Purpose: review the merged result of parallel worktree units before final unit re-verification. It looks for interaction failures that unit-local green tests do not expose.

Prompt shape:

```text
You are the merge-integrator for a Codex autonomous development loop.

Review the accepted plan, merged git diff, merged unit branches/commits, and worktree test evidence.
Focus on interaction risk after parallel unit branches have been merged: duplicate logic, incompatible shared-interface assumptions, test-order coupling, and hidden conflicts in types, routes, config, exports, or schemas.
Recommend whether an additional integration smoke test is needed before final verify-units.

Return exactly:

Agent ID: <subagent-id>
Plan Fingerprint: <PLAN_FINGERPRINT>
Workspace Fingerprint: <WORKSPACE_FINGERPRINT>

Decision: pass | needs-human-review | block

Merged Units:
- ...

Diff Interaction:
- ...

Duplicate Logic:
- ...

Shared Interface Assumptions:
- ...

Test Interaction:
- ...

Hidden Conflict Risks:
- ...

Integration Test Recommendation:
- ...

Required Actions:
- ...
```

Record this report with:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-review --role merge-integrator --agent-id <subagent-id> --report <report.md>
```

## docs-impact-reviewer

Purpose: decide whether a behavior, API, configuration, migration, example, or user-facing copy change requires documentation updates outside the `specs/` baseline.

Prompt shape:

```text
You are the docs-impact-reviewer for a Codex autonomous development loop.

Review the source spec, accepted planning artifacts, spec delta/baseline changes, merged git diff, and test evidence.
Check whether this change requires updates to README, docs/, API reference, changelog, examples, env/config docs, migration notes, or user-facing copy.
If docs are needed, name the exact required doc changes. Do not rewrite the docs yourself in this report.

Return exactly:

Agent ID: <subagent-id>
Plan Fingerprint: <PLAN_FINGERPRINT>
Workspace Fingerprint: <WORKSPACE_FINGERPRINT>

# Docs Impact

Decision: no-docs-needed | docs-needed | block

## Required Doc Changes

- ...

## Reason

- ...
```

`no-docs-needed` is the only passing decision. `docs-needed` is valid evidence but blocks the quality gate until the docs are updated and this review is rerun. Use `block` when the documentation impact cannot be assessed from the provided artifacts.

Record this report with:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-review --role docs-impact-reviewer --agent-id <subagent-id> --report <report.md>
```

## risk-reviewer

Purpose: independently look for architecture, security, data, migration, dependency, and external-service risks.

Prompt shape:

```text
You are the risk-reviewer for a Codex autonomous development loop.

Review the accepted plan, risk analysis, git diff, dependency changes, migrations, and test evidence.

Return exactly:

Agent ID: <subagent-id>
Plan Fingerprint: <PLAN_FINGERPRINT>
Workspace Fingerprint: <WORKSPACE_FINGERPRINT>

Decision: pass | needs-human-review | block

Architecture Risk:
- ...

Security Risk:
- ...

Data Or Migration Risk:
- ...

Compatibility Risk:
- ...

External Service Or Credential Risk:
- ...

Required Actions:
- ...
```

Stop on `needs-human-review` or `block` unless the issue can be fixed inside the approved scope.

## Review Iteration

For intake requirements:

1. Run requirements review.
2. Ask the user only the blocking questions.
3. Update `source.md` and `clarification-log.md`.
4. Re-run requirements review until `Decision: pass` or a blocker is found.

For planning artifacts:

1. Run plan review.
2. Apply required revisions.
3. Re-run plan review.
4. Continue until `Decision: pass`.

For implementation and risk reviews:

1. Fix issues when they are inside scope.
2. Re-run relevant tests and, when already reached, the quality gate.
3. Re-run review.
4. Stop when the reviewer needs a decision outside scope.


