---
name: codex-dev-loop
description: Run an end-to-end autonomous development loop from a Notion page, local Markdown spec, or clarified conversation to reviewed implementation, TDD-gated tests, spec baseline updates, ai-code-quality-gate, git commit, pushed branch, and pull request. Use when the agent must clarify a goal and acceptance criteria, size the task (small/standard/large gates), elaborate technical design, file scope, test plan, risk analysis, spec delta, and development plan, run Subagent reviews, implement units test-first (optionally in parallel git worktrees), merge spec deltas into the repository spec baseline, enforce quality gates, write execution records, and open GitHub PRs while stopping on ambiguity, repeated test failures, quality failures, architecture risk, or missing credentials.
---

# Codex Dev Loop

Current version: 0.5.1

## Operating Contract

Use this skill to drive a full local harness plus GitHub Actions loop.

- Load first-run preferences from `<loop-home>/config/codex-dev-loop.json` when present; otherwise use the default profile. `<loop-home>` is `~/.codex`, or `$CODEX_DEV_LOOP_HOME` when set (see Agent Adapters).
- Accept inputs from a Notion page, a local Markdown spec, or a clarification-first draft (`init --draft`).
- Start planning only when the source has a non-empty goal and acceptance criteria and a current `requirements-reviewer` pass; clarify with the user in the intake phase until every requirement is observable, falsifiable, bounded, explicit about non-goals, and mapped to at least one test.
- Agree on a task scale (`small`, `standard`, `large`) with the user before planning; the scale sets how heavy the gates are and is enforced by the harness.
- Produce technical design, file scope, test plan, risk analysis, spec delta, and development plan before coding.
- Run Subagent review loops until planning artifacts pass.
- Implement one independently testable unit at a time, test-first: record failing red evidence, then make it pass. Every green unit triggers `scope-check` so undeclared file drift, sensitive paths, and broad formatting noise stop the loop. Independent units may run in parallel through unit-implementer Subagents in isolated git worktrees.
- Reconcile the repository spec baseline (`specs/` by default) with the reviewed spec delta before implementation review, so spec updates ride the same PR as the code.
- Force tests through a hook or explicit gate, stopping at the configured failure limit.
- Require `$ai-code-quality-gate` (or the bundled fallback gate) before commit, using the configured quality profile.
- Create a new git branch, commit changes, push, and open a PR unless the configured automation level stops earlier.
- Inspect GitHub Actions required checks after opening the PR when GitHub access is available.
- Write execution records, review reports, quality summaries, and PR description artifacts; archive them after completion.
- Stop instead of guessing when requirements are unclear, architecture risk appears, external tokens are needed, or quality gates fail.

## Required Skills And Tools

- Use `$automated-dev-executor` for unit-by-unit implementation and forced test gates when installed; the bundled `scripts/test_gate.py` fallback runs the same evidence protocol otherwise.
- Use `$ai-code-quality-gate` for the configured lint, typecheck, test, Semgrep, CodeQL, Sonar, Qodana, Subagent alignment, and AI PR review gates when installed; the bundled `scripts/quality_gate_fallback.py` covers local gates otherwise.
- Use `scripts/dev_loop_harness.py` as the local state ledger for phases, scale, reviews, TDD evidence, test attempts, spec merges, quality gate, and PR records.
- Use `scripts/configure_dev_loop.py` to create or update first-run preferences.
- Use `multi_agent_v1` Subagents. If Subagents are unavailable, stop before the requirements or planning review:
  - `requirements-reviewer`
  - `plan-reviewer`
  - `merge-integrator` (parallel worktrees only; after merged branches, before `verify-units`)
  - `implementation-reviewer`
  - `docs-impact-reviewer`
  - `risk-reviewer`
  - `unit-implementer` (one per development unit; see [tdd-parallel-units.md](references/tdd-parallel-units.md))
- Use GitHub tooling or `gh` for pushing branches and opening PRs.
- Use Notion tools only when the input is a Notion page and the user has provided access.

## Agent Adapters

The harness is agent-neutral. On OpenAI Codex, follow this file as-is. On Claude Code, install per [adapters/claude-code/SKILL.md](adapters/claude-code/SKILL.md): set `CODEX_DEV_LOOP_HOME=~/.claude`, spawn reviewers and unit-implementers with the Agent tool instead of `multi_agent_v1`, and rely on the bundled gate fallbacks when the companion skills are absent. Gate-script overrides (`test_gate_script`, `quality_gate_script`) are honored only from the home-anchored config file.

## Composition — This Loop Orchestrates Composable Sub-Skills

This skill is the full-loop **orchestrator**. Each phase's methodology is defined once in a focused `dev-*` sub-skill; the orchestrator runs them in sequence under the harness state machine, which keeps all gates and evidence in `.codex/dev-loop/` (loop mode). The sub-skills also run standalone for small tasks — see [references/routing.md](references/routing.md) to decide whether a task needs the full loop at all.

| Phase | Methodology (canonical source) | In the loop |
| --- | --- | --- |
| Intake / clarification | [skills/dev-clarify](skills/dev-clarify/SKILL.md) | intake phase + `check-spec` + `requirements-reviewer` source-fingerprint gate on `source.md` |
| Planning | [skills/dev-plan](skills/dev-plan/SKILL.md) | planning artifacts under `.codex/dev-loop/` |
| Reviews | [skills/dev-review](skills/dev-review/SKILL.md) | `record-review` (loop-fingerprinted) |
| Implementation | [skills/dev-tdd](skills/dev-tdd/SKILL.md) + [tdd-parallel-units.md](references/tdd-parallel-units.md) | `run-test --stage red/green`, `record-test`, `verify-units` |
| Spec consolidation | [skills/dev-spec](skills/dev-spec/SKILL.md) | `record-spec-merge` |
| Ship | [skills/dev-ship](skills/dev-ship/SKILL.md) | `record-branch/commit/pr/cloud` |

Key rule: **methodology lives in the sub-skill; enforcement lives in the harness.** When a phase's discipline is unclear, read the sub-skill. The loop always uses the loop-mode harness commands (bound to plan/workspace fingerprints), never the `standalone-*` commands.

**Upgrade path.** If a task started as a standalone `dev-tdd` chain and grew into a full loop, run `adopt-evidence` during the implementation phase: it absorbs each standalone green whose workspace fingerprint still matches the current tree (re-stamping the red-before-green evidence to the current plan), so verified units are not re-run. Units without current standalone evidence run normally.

## First-Run Configuration

Before the first full run, check whether this file exists:

```text
<loop-home>/config/codex-dev-loop.json
```

If it is missing, ask the user to answer only these five setup questions, or run:

```bash
python <skill-dir>/scripts/configure_dev_loop.py
```

The five questions are:

1. Automation level: `pr_without_merge` (default), `commit_only`, or `planning_only`.
2. Source types: `markdown + notion` (default), `markdown`, or `notion`.
3. Quality profile: `standard` (default), `strict`, or `light`.
4. Test failure limit: number of automatic retries after a failure. `3` (default) blocks on the fourth consecutive failure; `0` blocks on the first failure. A passing run resets the counter.
5. Risk mode: `stop_and_ask` (default), `serious_only`, or `best_effort`.

Advanced keys get safe defaults and are edited directly in the JSON: `default_scale` (`standard`), `spec_dir` (`specs`), budget/time-box limits (`max_units`, `max_files_changed`, `max_test_retries_per_unit`, `max_review_iterations`, `max_quality_fix_rounds`, `max_diff_lines`), `test_gate_script`, `quality_gate_script`.

After saving configuration, respond with a concise confirmation such as:

```text
Automation scope is currently set to "Stop after PR creation"; tell me anytime if you want to adjust automation scope, source types, quality strictness, test retry count, or risk handling.
```

Default behavior when no config exists:

```json
{
  "automation_level": "pr_without_merge",
  "source_types": ["markdown", "notion"],
  "quality_profile": "standard",
  "test_failure_limit": 3,
  "max_units": 8,
  "max_files_changed": 20,
  "max_test_retries_per_unit": 3,
  "max_review_iterations": 3,
  "max_quality_fix_rounds": 2,
  "max_diff_lines": 1200,
  "risk_mode": "stop_and_ask",
  "default_scale": "standard",
  "spec_dir": "specs"
}
```

## Loop Overview

1. Intake the source spec (or a draft) and clarify it until goal and acceptance criteria are concrete and test-mappable.
2. Run `requirements-reviewer`; revise or ask the user again until the current `source.md` passes.
3. Agree on the task scale with the user.
4. Generate planning artifacts, including the spec delta.
5. Run plan Subagent review; revise until it passes.
6. Create a new branch.
7. Implement units test-first (red, then green), serially or in parallel worktrees.
8. Merge the spec delta into the repository spec baseline and record it.
9. If any worktree evidence exists, run `merge-integrator` against the merged tree before `verify-units`.
10. Re-verify every unit in the main workspace (`verify-units`) after merges and spec edits.
11. Run implementation Subagent alignment review.
12. Run `docs-impact-reviewer`; update required docs and re-review until it returns `no-docs-needed`.
13. Run risk Subagent review (small scale may skip it when the sensitive-path guard stays clean).
14. Run `$ai-code-quality-gate`.
15. Commit, push, and open a PR.
16. Inspect GitHub Actions required checks when GitHub access is available.
17. Write back records, final status, and archive the run.

## Intake And Clarification

For local Markdown, read the file directly.

For Notion, fetch the page content and save a local copy under:

```text
.codex/dev-loop/source.md
```

Initialize local loop state before anything else:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop init --source <source.md> --source-type markdown --scale <small|standard|large>
```

- Use `--source-type notion` when the source was fetched from Notion. The harness refuses source types that are disabled by first-run configuration.
- When the user has only a rough idea and no spec document, start with `init --draft`: the harness writes a skeleton `source.md` and the loop starts in the `intake` phase.
- If a previous run was not archived, `init` refuses; run `archive` (or pass `--force` deliberately).

The loop starts in the `intake` phase. Before advancing:

1. Read the source. If the goal, acceptance criteria, constraints, or scope boundaries are unclear, ask the user focused questions ? one round at a time, most load-bearing questions first.
2. Record every question, answer, and user-approved assumption in `.codex/dev-loop/clarification-log.md`.
3. Write the clarified goal and acceptance criteria into `source.md` (`## Goal`, `## Acceptance Criteria`). Each acceptance criterion must be expressible as given conditions, action, observable result, and failure condition.
4. Capture the source fingerprint:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop fingerprint
```

5. Spawn `requirements-reviewer` with only `source.md`, `clarification-log.md`, and `SOURCE_FINGERPRINT`. It must check every requirement for observability, falsifiability, boundaries, explicit non-goals, and at least one test mapping. It must not invent missing requirements; on gaps, ask for the smallest blocking questions.
6. Save the report under `.codex/dev-loop/reviews/requirements-reviewer.md` and record it:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-review --role requirements-reviewer --agent-id <subagent-id> --report <report.md>
```

7. Propose a task scale with a one-line reason (for example "single-file fix, no dependency changes: small") and confirm it with the user unless the user already chose one.

Advance only when the source is ready; the harness enforces non-empty Goal and Acceptance Criteria plus a current `requirements-reviewer` pass for `source.md`:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop set-phase planning
```

If planning or plan review reveals the requirement is still ambiguous, backtrack to `intake` (`set-phase intake`), clarify again, and redo the invalidated work.

## Task Scale

Scale is recorded in loop state and enforced by the harness:

- `small` — single bounded change. Planning artifacts keep all files and headings but only the technical design must contain real content; the `risk_review` phase may be skipped when the sensitive-path guard stays clean. TDD evidence and all other gates still apply.
- `standard` — the default; the full phase sequence and current artifact content rules.
- `large` — every required artifact section must be filled in; use for multi-module or high-risk work.

Rules:

- Set the initial scale at `init --scale ...`; change it with `set-scale <scale>`.
- Raising the scale is allowed at any phase; heavier gates apply immediately and may require redoing gates (for example a real risk review, or richer planning artifacts).
- Lowering the scale is only allowed during `intake` or `planning`.
- Hard guard: the harness refuses the small-scale `risk_review` skip when the change set (staged, unstaged, or untracked) touches dependency manifests, lockfiles, migrations, SQL, CI/CD or Docker files, Terraform, keys or certificates, or paths under auth/security/secrets/crypto directories. Escalate with `set-scale standard` and run the real risk review.
- Do not use `small` to smuggle risk: if in doubt, stay at `standard`.

## Planning Artifacts

Before coding, create or update these files:

```text
.codex/dev-loop/technical-design.md
.codex/dev-loop/test-plan.md
.codex/dev-loop/risk-analysis.md
.codex/dev-loop/development-plan.md
.codex/dev-loop/spec-delta.md
.codex/dev-loop/decision-log.md
```

Use [artifact-templates.md](references/artifact-templates.md) for required headings.

The planning artifacts must include:

- Technical design.
- Expected file/module scope.
- Test plan.
- Risk analysis.
- Spec delta: requirement-level changes per capability (see [spec-baseline.md](references/spec-baseline.md)), or a justified `## No Spec Impact`.
- Development plan split into independently testable units, each with:
  - `- TDD: red` (default) — a failing red-stage test is required before green counts.
  - `- TDD: regression-only` — only for changes fully covered by existing tests (pure refactors); the plan must justify it, and plan review must approve it.
  - `- Dependencies:` — used to decide which units may run in parallel.
- Required tools and credentials.
- External service calls with reasons.

Do not start coding until plan review passes. Changing any planning artifact (including `spec-delta.md`) after review invalidates the review by fingerprint; revise and re-review.

## Subagent Review Loop

Read [subagent-review-loop.md](references/subagent-review-loop.md) before spawning reviewers.

Requirements review loop:

1. Spawn `requirements-reviewer` during `intake`, before `set-phase planning`.
2. Ask for `Decision: pass | needs-revision | block`.
3. Save the review under `.codex/dev-loop/reviews/requirements-reviewer.md`.
4. Ensure the report includes `Agent ID:` and `Source Fingerprint:` from the current harness state.
5. Record it with `scripts/dev_loop_harness.py record-review --role requirements-reviewer --agent-id <subagent-id> --report <report.md>`.
6. If `needs-revision`, ask the user only the blocking clarification questions, update `source.md`, and re-review.
7. If `block`, stop with a blocker.
8. Continue to planning only on `pass`.

Planning review loop:

1. Spawn `plan-reviewer` with only source spec and planning artifacts.
2. Ask for `Decision: pass | needs-revision | block`.
3. Save the review under `.codex/dev-loop/reviews/plan-reviewer.md`.
4. Ensure the report includes `Agent ID:` and `Plan Fingerprint:` from the current harness state.
5. Record it with `scripts/dev_loop_harness.py record-review --role plan-reviewer --agent-id <subagent-id> --report <report.md>`.
6. If `needs-revision`, revise artifacts and re-review.
7. If `block`, stop with a blocker.
8. Continue only on `pass`.

Merge integration review loop (parallel worktrees only):

1. After all worktree unit branches and spec baseline changes are merged into the main workspace, but before `verify-units`, spawn `merge-integrator`.
2. Give it the accepted plan, merged git diff, list of merged unit branches/commits, and worktree test evidence.
3. Ask for `Decision: pass | needs-human-review | block`.
4. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, and `Workspace Fingerprint:`.
5. Save and record it with `scripts/dev_loop_harness.py record-review --role merge-integrator --agent-id <subagent-id> --report <report.md>`.
6. If it reports duplicate logic, conflicting interface assumptions, test-order coupling, hidden type/route/config/export/schema conflicts, or a needed integration test, fix or escalate before `verify-units`.

Implementation review loop:

1. After implementation, spec merge, and unit verification, spawn `implementation-reviewer`.
2. Give it source spec, planning artifacts, git diff (including spec baseline changes), and test evidence.
3. Save output to `.codex/quality-gate/subagent-alignment.md`.
4. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, and `Workspace Fingerprint:`.
5. Also record it with `scripts/dev_loop_harness.py record-review --role implementation-reviewer --agent-id <subagent-id> --report <report.md>`.
6. Continue only if the report says `Decision: pass`.

Docs impact review loop:

1. After implementation-reviewer passes, spawn `docs-impact-reviewer` before the quality gate.
2. Give it source spec, planning artifacts, merged git diff, spec-delta/spec baseline changes, and any existing README/docs/API/changelog/examples/env/config/migration/user-copy files relevant to the change.
3. Ask for `Decision: no-docs-needed | docs-needed | block`.
4. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, `Workspace Fingerprint:`, `# Docs Impact`, `## Required Doc Changes`, and `## Reason`.
5. Record it with `scripts/dev_loop_harness.py record-review --role docs-impact-reviewer --agent-id <subagent-id> --report <report.md>`.
6. If it returns `docs-needed`, update the required docs inside the approved scope and re-run implementation tests/reviews as needed before recording a new docs-impact review.
7. The harness blocks `quality_gate` until the current workspace has `Decision: no-docs-needed`.

Risk review loop:

1. Spawn `risk-reviewer` after implementation alignment passes (skippable only at small scale with a clean guard).
2. Give it risk analysis, git diff, dependency changes, migrations, and test evidence.
3. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, and `Workspace Fingerprint:`.
4. Save and record it with `scripts/dev_loop_harness.py record-review --role risk-reviewer --agent-id <subagent-id> --report <report.md>`.
5. If it finds architecture, data, security, or external-service risk, stop unless the issue can be fixed without changing scope.

## Development Loop

Read [tdd-parallel-units.md](references/tdd-parallel-units.md) before implementing.

TDD inside every unit (mode `red`):

1. Write the smallest test that proves the unit's missing behavior.
2. Run the red stage with the intended failure reason; the built-in red-test-validator rejects import, syntax, environment, path, and ambiguous snapshot failures before they can count as red evidence:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-test --unit dev-001 --stage red --expected-failure "401 error message is missing" --command "<test command>"
```

You can inspect an existing red log directly with:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop validate-red --unit dev-001 --log <red.log> --expected "401 error message is missing"
```

3. Implement until the test passes, then record the green stage (the harness refuses green without red evidence and runs `scope-check` after a green pass):

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-test --unit dev-001 --command "<test command>"
```

4. Refactor with the test green; re-run the green gate after refactors. If scope-check fails, either remove the drift, update the reviewed plan/design scope and re-review, or raise scale for sensitive-path work before proceeding.

A red run that unexpectedly passes proves nothing: strengthen the test or re-plan the unit. A red run that fails for the wrong reason is recorded for audit but does not unlock green. `regression-only` units skip the red stage but still need their green gate.

Serial execution: work on exactly one unit at a time with `$automated-dev-executor`, in dependency order.

Parallel execution (independent units only):

1. Pick units whose `- Dependencies:` are all complete.
2. For each, create an isolated worktree: `git worktree add <path> -b <branch>-<unit>`.
3. Spawn a `unit-implementer` Subagent per worktree. It writes the failing test, runs the test gate script directly inside the worktree, implements, reruns to green, commits, and returns the `AUTODEV_TEST_META` paths.
4. The orchestrator (you) records all evidence serially — never let Subagents touch loop state:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-test --unit dev-001 --stage red --meta <meta.json> --worktree <path>
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-test --unit dev-001 --meta <meta.json> --worktree <path>
```

5. Merge each unit branch back into the loop branch; remove the worktree (`git worktree remove <path>`).

Worktree evidence is interim by design: its workspace fingerprint does not match the merged main tree. When any worktree evidence exists, the harness blocks `verify-units` until a current `merge-integrator` review has passed.

Finishing the implementation phase, in this order:

1. All units implemented and merged into the loop branch.
2. Merge the spec delta into the spec baseline and record it (next section).
3. If any worktree evidence exists, run and record `merge-integrator` against the current merged tree.
4. Re-verify every unit against the final tree:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop verify-units
```

Rules:

- Retry a failing green gate only up to `max_test_retries_per_unit`; the counter tracks consecutive failures (red runs excluded) and resets on a pass.
- Respect budget/time-box limits: `max_units`, `max_files_changed`, `max_diff_lines`, `max_review_iterations`, and `max_quality_fix_rounds` stop the loop with a blocker instead of expanding scope or continuing to iterate.
- Do not advance beyond implementation until every `## Unit dev-*` has red evidence (or an approved waiver) and a current green pass.
- For parallel worktrees, do not run `verify-units` until `merge-integrator` passes for the current merged tree.
- After the configured retry limit is exceeded, stop with a blocker.
- Record command, result, timestamp, and log path for every attempt.
- Do not skip tests or mark a failing unit complete.

## Spec Baseline Merge

Read [spec-baseline.md](references/spec-baseline.md) for the delta format and merge rules.

The repository keeps living specs under `<spec_dir>/` (default `specs/`), one file per capability. During implementation, after the code lands:

1. Run scope-check on the current implementation diff before editing the spec baseline. Fix undeclared drift before spec changes make the diff harder to read.
2. Apply `spec-delta.md` to the baseline: add, update, or delete the `#### Requirement:` blocks in `specs/<capability>.md` (create the file for a new capability).
2. Record and validate the merge — the harness checks every ADDED/MODIFIED title exists and every REMOVED title is gone:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-spec-merge
```

3. Run `verify-units` afterwards so test evidence covers the final tree including spec files.

The spec baseline update is part of the branch, so reviewers and the PR see requirement changes next to the code. Implementation review and later phases are blocked until the recorded merge is current. If the change has no requirement-level impact, say why under `## No Spec Impact` in `spec-delta.md` and still run `record-spec-merge`.

## Quality Gate

After all implementation units pass and the spec merge is current:

1. Save Subagent alignment output to `.codex/quality-gate/subagent-alignment.md`.
2. Run `$ai-code-quality-gate` with required gates from the configured quality profile.
3. Run and record the result with `scripts/dev_loop_harness.py run-quality`.
4. If a required scanner needs a local dependency or CLI install, install it only when it is required by the repo's configured gate.
5. If a scanner needs remote credentials or a hosted service that is not already configured, stop and ask the user.
6. Stop on quality gate failure.

Recommended harness command:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-quality
```

The harness resolves the gate script in this order: home-anchored config override, the `ai-code-quality-gate` companion skill, the bundled `quality_gate_fallback.py`. It runs the equivalent of:

```bash
python <loop-home>/skills/ai-code-quality-gate/scripts/quality_gate.py \
  --workspace . \
  --require <extra-gates> \
  --alignment-report .codex/quality-gate/subagent-alignment.md
```

For `strict` profile the harness also passes `--strict`. Configured profile gates are always required; `run-quality --require` can only add gates, not replace or weaken the profile. The harness requires real quality gate output and verifies that all gates required by the configured profile pass. PR-level AI review is enforced later in the cloud check stage for standard and strict profiles.

## External Service Policy

Allowed without extra confirmation:

- Installing project dependencies needed to run local tests or configured gates.
- Calling GitHub APIs or `gh` for branch, push, PR, and check status operations.
- Reading Notion only when the source input is a Notion page and the connector is available.

Require explicit user confirmation before calling:

- SonarCloud/SonarQube remote services when not already configured in the repo.
- Qodana Cloud when not already configured in the repo.
- Qodo, CodeRabbit, Greptile, or other AI review SaaS beyond existing GitHub App checks.
- Any non-GitHub external API, hosted scanner, telemetry service, or paid service.

## Git And PR Flow

Read [git-pr-flow.md](references/git-pr-flow.md) before modifying git state. Read [github-actions-cloud.md](references/github-actions-cloud.md) after opening the PR.

Rules:

- Never commit directly to `main`.
- Create a new branch for every loop.
- Record the branch before implementation:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-branch --branch <branch>
```

- Commit only after tests, Subagent reviews, spec merge, and `$ai-code-quality-gate` pass.
- In `commit_only` automation, record the committed HEAD before completing:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-commit
```

- Push the branch and open a PR.
- Include design, tests, spec delta summary, risk, quality gate summary, and Subagent review summary in the PR body.
- Inspect GitHub Actions checks when available and record the result.
- Record branch, commit, and PR URL with `scripts/dev_loop_harness.py record-pr`; the harness verifies them with `gh pr view` and checks that the PR repository matches local `origin`.
- Record cloud checks with `scripts/dev_loop_harness.py record-cloud --status passed`; the harness verifies them with `gh pr checks`, matches required checks by exact canonical name or by known scanner aliases (for example `SonarCloud Code Analysis` satisfies `sonar`), and does not let unrelated optional failures block the loop.
- `record-pr --allow-local-simulation` and `record-cloud --allow-local-simulation` are self-test only and require `CODEX_DEV_LOOP_TEST_MODE=1`.

Stop if:

- The repository is not a git repo.
- The worktree has unrelated dirty changes that conflict with the task.
- GitHub auth is unavailable.
- Branch creation, push, or PR creation fails.
- Required GitHub Actions workflow or required checks are absent and cannot be added within the approved repo changes.

## Blockers And Backtracking

Advance phases only through the harness:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop set-phase <phase>
```

The harness rejects illegal jumps such as `planning -> complete`. When the loop is blocked, first resolve the blocker with a written reason before backtracking:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop resolve-blocker --reason "<what was fixed>"
```

Resolutions are appended to `.codex/dev-loop/blocker-resolutions.md` and kept in loop state; after resolving, backtrack with `set-phase` and redo the invalidated work. When the loop backtracks to an earlier phase, the harness clears downstream test, review, spec-merge, quality, PR, and cloud-check state so stale passes cannot be reused.

Before asking Subagents to review current artifacts, capture evidence fingerprints:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop fingerprint
```

Review reports must echo these fingerprints so stale reports cannot be reused after plan or code changes.

## Writeback And Archive

Always write local records under:

```text
.codex/dev-loop/
```

If the input came from Notion, write a concise final status back to the Notion page only when Notion tools are available and the user has authorized it.

Final records must include:

- Source spec copy and clarification log.
- Technical design.
- Test plan.
- Risk analysis.
- Development plan with TDD evidence per unit.
- Spec delta and recorded baseline merge.
- Subagent review outputs.
- Test evidence paths.
- Quality gate summary.
- GitHub Actions check summary.
- Commit hash.
- PR URL.
- Known follow-ups.

After the loop reaches `complete`, archive the run so the next loop starts clean:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop archive
```

Records move to `.codex/dev-loop-archive/<timestamp>-<branch>/`; the spec baseline under `<spec_dir>/` stays in place as the living documentation.

## Stop Conditions

Stop and report a blocker when:

- Requirements stay unclear after clarification rounds, `requirements-reviewer` does not pass, or the user is unavailable to answer a load-bearing question.
- Plan review returns `block`.
- Test gate exceeds `max_test_retries_per_unit` with consecutive failures on the same unit.
- A budget/time-box limit is reached (`max_units`, `max_files_changed`, `max_diff_lines`, `max_review_iterations`, or `max_quality_fix_rounds`). Stop and report; do not continue expanding scope or fixing opportunistically.
- A red-stage test cannot be made to fail (the planned behavior may already exist or the unit is mis-scoped).
- Scope-check finds undeclared file drift, sensitive-path drift requiring a higher scale/risk review, undeclared dependency manifests, or broad formatting noise.
- The spec baseline cannot be reconciled with the reviewed spec delta.
- `$ai-code-quality-gate` fails.
- Subagent alignment returns anything other than `Decision: pass`.
- Risk review finds architecture, security, data, migration, compatibility, or external-service risk that needs a user decision.
- Required external credentials or tokens are missing.
- A non-GitHub external service would be called without user approval.
- Git branch, commit, push, or PR creation cannot complete.
- GitHub Actions required checks are absent, fail, or need missing secrets.



