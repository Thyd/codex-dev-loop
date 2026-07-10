# TDD And Parallel Units

## Contents

- [TDD stages per unit](#tdd-stages-per-unit)
- [Serial mode](#serial-mode)
- [Parallel mode](#parallel-mode-independent-units-only)
- [unit-implementer Subagent](#unit-implementer-subagent)
- [Failure handling](#failure-handling)

## TDD Stages Per Unit

Every `## Unit dev-*` carries a `- TDD:` field in `development-plan.md`:

- `red` (default): a recorded failing test is required before any green run counts.
- `regression-only`: existing tests already cover the change (pure refactor). The plan must justify this and plan review must approve it; the harness rejects any other value.

Red stage rules:

- The red test must fail because the behavior is missing, not because the test harness is broken. The red-test-validator rejects import errors, syntax errors, missing dependencies, path/environment failures, and ambiguous snapshot drift. `timeout` and `error` outcomes do not count as red evidence.
- A red run that passes is a finding, not progress: the behavior may already exist, or the test is vacuous. Strengthen the test or re-plan the unit.
- Red attempts never count against the test failure limit.
- Red evidence binds to the plan fingerprint; changing planning artifacts invalidates it. Invalid red attempts remain in the ledger for audit but do not unlock green.

Green stage rules:

- The harness refuses a green run for a `red`-mode unit without current red evidence.
- After a green pass, the harness runs scope-check against the current diff. The unit is not allowed forward if changed files are outside declared scope, sensitive paths need scale/risk escalation, dependency manifests are undeclared, or formatting noise is broad.
- The unit is complete when its latest attempt is a green pass whose fingerprints match the current plan and workspace and scope-check has passed.

## Serial Mode

Work through units in dependency order with `$automated-dev-executor`, one at a time, using `run-test --stage red --expected-failure "<intended missing behavior>"` then `run-test` in the main workspace.

## Parallel Mode (independent units only)

Only parallelize units whose `- Dependencies:` are all complete. Keep the batch small (2-3 worktrees) unless the repo's tests are cheap.

Orchestrator responsibilities (never delegate these):

1. Create one isolated worktree per unit from the loop branch:

```bash
git worktree add ../wt-dev-002 -b <loop-branch>-dev-002
```

2. Spawn one `unit-implementer` Subagent per worktree.
3. Serialize all harness calls yourself. Subagents must never write loop state; two concurrent `record-test` calls can race on `loop-state.json`.
4. After each unit finishes: record its evidence, merge the unit branch back into the loop branch, resolve conflicts, remove the worktree (`git worktree remove ../wt-dev-002`).
5. After ALL unit branches and spec baseline changes are merged, run and record `merge-integrator` against the current merged tree.
6. Run `verify-units` in the main workspace. Worktree evidence is interim: its workspace fingerprint will not match the merged tree, and the harness refuses `verify-units` until the merge-integrator review passes.

Manual preflight is available at any point:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop scope-check --plan .codex/dev-loop/development-plan.md --design .codex/dev-loop/technical-design.md
```

Record worktree evidence with:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-test --unit dev-002 --stage red --expected-failure "<intended missing behavior>" --meta <meta.json> --worktree ../wt-dev-002
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-test --unit dev-002 --meta <meta.json> --worktree ../wt-dev-002
```

The harness only accepts linked worktrees of the main workspace (created with `git worktree add`).

Post-merge flow:

```text
unit branches green
-> merge branches
-> merge spec baseline changes, if any
-> merge-integrator review
-> integration smoke test, if recommended
-> verify-units
```

The merge-integrator should recommend `needs-human-review` or `block` when merged units duplicate logic, change a public interface with incompatible assumptions, introduce order-dependent tests, hide route/config/export/schema/type conflicts, or need a new integration smoke test before final re-verification.

## unit-implementer Subagent

Purpose: implement exactly one development unit test-first inside an isolated worktree.

Prompt shape:

```text
You are the unit-implementer for development unit <unit-id> in an autonomous dev loop.

Worktree: <absolute worktree path> (work ONLY here; never touch the main workspace or .codex/dev-loop)
Unit objective, scope, acceptance, and test gate: <paste the unit block from development-plan.md>
Relevant design excerpt: <paste the minimal technical-design context>

Steps:
1. Write the smallest failing test that proves the unit's missing behavior.
2. Run the test gate script directly and keep the failing (red) metadata. Tell the orchestrator the expected failure reason so `record-test --stage red --expected-failure ...` can validate it:
   python <skill-dir>/scripts/test_gate.py --unit <unit-id> --command "<test command>" --cwd <worktree>
3. Implement the unit until the same command passes (green). Do not weaken the test.
4. Commit your changes in the worktree branch with a conventional message.
5. Return exactly:

Unit: <unit-id>
Red Meta: <path from AUTODEV_TEST_META of the failing run>
Green Meta: <path from AUTODEV_TEST_META of the passing run>
Commit: <sha>
Notes:
- <surprises, scope deviations, or follow-ups; "none" otherwise>

Constraints:
- Stay inside the unit's declared file scope; report any needed out-of-scope change in Notes instead of making it.
- Never edit loop state, planning artifacts, or the spec baseline.
- Never mark the unit done with a failing or skipped test.
```

Use the `automated-dev-executor` test gate script when installed; otherwise use the bundled `<skill-dir>/scripts/test_gate.py` (same protocol).

## Failure Handling

- A unit-implementer that cannot make its red test fail, or cannot reach green inside the retry budget, reports back; the orchestrator records the failing attempts (they count toward the shared limit) and stops with a blocker if the limit is exceeded.
- Merge conflicts between unit branches are resolved by the orchestrator in the main workspace; `merge-integrator` checks cross-unit interaction risk before `verify-units` catches runnable regressions.

