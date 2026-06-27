# Subagent Review Loop

Use three independent Subagent roles. Give each role raw artifacts and a narrow task.

Do not pass your intended answer, hidden conclusions, or desired outcome. The point is cross-checking.

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

## implementation-reviewer

Purpose: verify that the code diff matches the PR objective and planning artifacts.

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
