---
name: codex-dev-loop
description: Run an end-to-end, evidence-gated development loop for standard, multi-module, high-risk, or explicitly full-pipeline work, from a Notion page, Markdown spec, or clarified conversation through reviewed implementation, TDD, living-spec updates, quality gates, commit, push, and pull request. Use when the work needs coordinated planning, independent reviewer agents, multiple testable units, risk controls, or complete PR automation. Do NOT use for one bounded low-risk behavior, plan-only work, review-only work, or root-cause debugging; route those to the focused dev-* skills instead.
---

# Codex Dev Loop

Current version: 0.7.0

## Operating Contract

Drive the full loop through `scripts/dev_loop_harness.py`; treat its phase,
fingerprint, scope, budget, evidence, and transition checks as authoritative.

- Keep one evidence source per workspace. Full-loop records live under
  `.codex/dev-loop/`; never call standalone write commands while a loop is active.
- Clarify Goal and Acceptance Criteria and record a current
  `requirements-reviewer` pass before planning.
- Confirm scale, create every planning artifact, and obtain a current
  `plan-reviewer` pass before coding.
- Implement independently testable units test-first. A valid failing red run
  must precede green unless the reviewed plan explicitly allows
  `regression-only`.
- Keep tests, spec merge, reviews, quality, commit, PR, and cloud evidence bound
  to current plan/workspace fingerprints; changed inputs invalidate old passes.
- Stop at ambiguity, hard risk, exhausted budgets, missing credentials, or a
  failed required gate. Never weaken gates to make the loop finish.

## Preflight

1. Read [routing.md](references/routing.md). If the task is bounded and
   low-risk, route to the matching `dev-*` skill instead of starting this loop.
2. Load `<loop-home>/config/codex-dev-loop.json`; run
   `scripts/configure_dev_loop.py` when first-run preferences are missing.
3. Run `doctor` before resuming older evidence. If it reports
   `needs-migration`, read [evidence-contracts.md](references/evidence-contracts.md),
   preview `migrate-evidence --dry-run`, then migrate.
4. Inspect existing `.codex/dev-loop/loop-state.json`. Resume an active loop;
   archive a completed run before initializing another.
5. Read [full-loop-workflow.md](references/full-loop-workflow.md) before the
   first state-changing command. It is the canonical end-to-end command order.

Initialize a local Markdown source (use `--source-type notion` only after an
authorized fetch, or `--draft` for a rough idea):

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  init --source <source.md> --source-type markdown \
  --scale <small|standard|large>
```

## Load Details On Demand

Read only the references needed for the active phase:

| Need | Canonical reference |
| --- | --- |
| End-to-end commands, configuration, recovery, stop rules | [full-loop-workflow.md](references/full-loop-workflow.md) |
| Artifact headings and field schemas | [artifact-templates.md](references/artifact-templates.md) |
| Reviewer inputs, reports, decisions, remediation | [subagent-review-loop.md](references/subagent-review-loop.md) |
| Red/green evidence, worktrees, unit implementers | [tdd-parallel-units.md](references/tdd-parallel-units.md) |
| Living spec delta and merge semantics | [spec-baseline.md](references/spec-baseline.md) |
| Branch, commit, push, and PR rules | [git-pr-flow.md](references/git-pr-flow.md) |
| Required GitHub Actions checks | [github-actions-cloud.md](references/github-actions-cloud.md) |
| Evidence schema, JSON output, migration | [evidence-contracts.md](references/evidence-contracts.md) |

For Claude Code, also read
[adapters/claude-code/SKILL.md](adapters/claude-code/SKILL.md), set
`CODEX_DEV_LOOP_HOME=~/.claude`, and map fresh reviewers to its Agent tool.

## Composition

Methodology lives in the focused skill; enforcement stays in the shared
harness. Inside a full loop, use loop-mode commands rather than standalone
commands.

| Phase | Methodology | Enforced evidence |
| --- | --- | --- |
| Intake | [dev-clarify](skills/dev-clarify/SKILL.md) | source + clarification log + requirements review |
| Planning | [dev-plan](skills/dev-plan/SKILL.md) | design/test/risk/development/spec artifacts |
| Reviews | [dev-review](skills/dev-review/SKILL.md) | fresh agent identity + current fingerprints |
| Implementation | [dev-tdd](skills/dev-tdd/SKILL.md) | `run-test --stage red`, green, scope and budget checks |
| Spec | [dev-spec](skills/dev-spec/SKILL.md) | `record-spec-merge` against the baseline |
| Delivery | [dev-ship](skills/dev-ship/SKILL.md) | branch/commit/PR/cloud records |

If standalone `dev-tdd` work grows into a full loop, initialize and reach
implementation, then run `adopt-evidence`. Only green evidence matching the
current workspace fingerprint is imported.

## Required Agents And Gates

Use the host's current collaboration API to spawn a fresh independent agent for
each required role. Do not reuse the author's reasoning pass as review.

| Role | Gate |
| --- | --- |
| `requirements-reviewer` | before planning |
| `plan-reviewer` | before branch/implementation |
| `merge-integrator` | after parallel merges, before final `verify-units` |
| `implementation-reviewer` | after final-tree tests and spec merge |
| `docs-impact-reviewer` | before risk/quality; must return `no-docs-needed` |
| `risk-reviewer` | before quality; small may skip only with a clean hard guard |
| `unit-implementer` | one per independent worktree unit |

If independent agents are unavailable, stop before requirements or plan review.
Use `$automated-dev-executor` for unit execution and `$ai-code-quality-gate` for
configured gates when installed; bundled fallbacks preserve the same evidence
protocol when companion skills are absent.

## Phase Spine

Advance only through harness transitions:

1. Intake and clarify; fingerprint and record `requirements-reviewer`.
2. Confirm scale; create artifacts and record `plan-reviewer`.
3. Create and record a feature branch.
4. For each unit, record `run-test --stage red` then current green evidence.
5. Merge parallel worktrees; record `merge-integrator` when applicable.
6. Apply and `record-spec-merge`; run final-tree `verify-units`.
7. Record implementation, docs-impact, and required risk reviews.
8. Run and record `run-quality`.
9. Commit; for full automation push, open, verify, and `record-pr`.
10. Verify and record required cloud checks, complete, write final records, and
    `archive`.

Changing reviewed plans, source, code, specs, reports, or git state may
invalidate downstream evidence. Re-run the affected gate rather than copying or
editing ledger JSON by hand.

## Non-Negotiable Guards

- `small` never bypasses sensitive dependency, migration, CI, infrastructure,
  credential, auth, security, secret, or crypto changes; raise scale and run a
  real risk review.
- Never commit on `main`, `master`, `develop`, or `release/*`.
- Never accept red failures caused by imports, syntax, collection, tooling,
  dependencies, environment, path, or ambiguous snapshots.
- Never let subagents write shared loop state; the orchestrator records their
  returned evidence serially.
- Never call unconfigured hosted scanners, paid services, telemetry, third-party
  AI review SaaS, or non-GitHub APIs without explicit user confirmation.
- `run-quality --require` may add required gates but cannot replace configured
  gates. Stop on failure.
- PR/cloud simulation flags are self-test only and require
  `CODEX_DEV_LOOP_TEST_MODE=1`.

## Completion Or Blocker

Respect `planning_only`, `commit_only`, and `pr_without_merge`. Completion must
match the configured automation level and retain current local evidence,
including source/clarification, plans, reviews, tests, spec merge, quality,
commit, and—when applicable—PR/cloud records.

A run is not complete until `archive` succeeds and `.codex/dev-loop/` no longer exists.
Verify the archive path before the final response; `phase: complete` alone is
not a completed delivery.

When blocked, report the active phase/unit, changed files, last evidence path,
exact blocker, decision needed, recommended option, alternatives, and resume
command. Resolve recorded blockers through `resolve-blocker`; backtracking
clears stale downstream state. Do not declare completion while any required
gate is missing or stale.
