---
name: codex-dev-loop
description: Run an end-to-end autonomous development loop from a Notion page, local Markdown spec, or clarified conversation to reviewed implementation, TDD-gated tests, spec baseline updates, ai-code-quality-gate, git commit, pushed branch, and pull request. Use when the agent must clarify a goal and acceptance criteria, size the task (small/standard/large gates), elaborate technical design, file scope, test plan, risk analysis, spec delta, and development plan, run Subagent reviews, implement units test-first (optionally in parallel git worktrees), merge spec deltas into the repository spec baseline, enforce quality gates, write execution records, and open GitHub PRs while stopping on ambiguity, repeated test failures, quality failures, architecture risk, or missing credentials.
---

# Codex Dev Loop

Current version: 0.4.0

## Operating Contract

Use this skill to drive a full local harness plus GitHub Actions loop.

- Load first-run preferences from `<loop-home>/config/codex-dev-loop.json` when present; otherwise use the default profile. `<loop-home>` is `~/.codex`, or `$CODEX_DEV_LOOP_HOME` when set (see Agent Adapters).
- Accept inputs from a Notion page, a local Markdown spec, or a clarification-first draft (`init --draft`).
- Start planning only when the source has a non-empty goal and acceptance criteria; clarify with the user in the intake phase until it does.
- Agree on a task scale (`small`, `standard`, `large`) with the user before planning; the scale sets how heavy the gates are and is enforced by the harness.
- Produce technical design, file scope, test plan, risk analysis, spec delta, and development plan before coding.
- Run Subagent review loops until planning artifacts pass.
- Implement one independently testable unit at a time, test-first: record failing red evidence, then make it pass. Independent units may run in parallel through unit-implementer Subagents in isolated git worktrees.
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
- Use `multi_agent_v1` Subagents. If Subagents are unavailable, stop before planning review:
  - `plan-reviewer`
  - `implementation-reviewer`
  - `risk-reviewer`
  - `unit-implementer` (one per development unit; see [tdd-parallel-units.md](references/tdd-parallel-units.md))
- Use GitHub tooling or `gh` for pushing branches and opening PRs.
- Use Notion tools only when the input is a Notion page and the user has provided access.

## Agent Adapters

The harness is agent-neutral. On OpenAI Codex, follow this file as-is. On Claude Code, install per [adapters/claude-code/SKILL.md](adapters/claude-code/SKILL.md): set `CODEX_DEV_LOOP_HOME=~/.claude`, spawn reviewers and unit-implementers with the Agent tool instead of `multi_agent_v1`, and rely on the bundled gate fallbacks when the companion skills are absent. Gate-script overrides (`test_gate_script`, `quality_gate_script`) are honored only from the home-anchored config file.

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

Advanced keys get safe defaults and are edited directly in the JSON: `default_scale` (`standard`), `spec_dir` (`specs`), `test_gate_script`, `quality_gate_script`.

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
  "risk_mode": "stop_and_ask",
  "default_scale": "standard",
  "spec_dir": "specs"
}
```

## Loop Overview

1. Intake the source spec (or a draft) and clarify it until goal and acceptance criteria are unambiguous.
2. Agree on the task scale with the user.
3. Generate planning artifacts, including the spec delta.
4. Run plan Subagent review; revise until it passes.
5. Create a new branch.
6. Implement units test-first (red, then green), serially or in parallel worktrees.
7. Merge the spec delta into the repository spec baseline and record it.
8. Re-verify every unit in the main workspace (`verify-units`) after merges and spec edits.
9. Run implementation Subagent alignment review.
10. Run risk Subagent review (small scale may skip it when the sensitive-path guard stays clean).
11. Run `$ai-code-quality-gate`.
12. Commit, push, and open a PR.
13. Inspect GitHub Actions required checks when GitHub access is available.
14. Write back records, final status, and archive the run.

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

1. Read the source. If the goal, acceptance criteria, constraints, or scope boundaries are unclear, ask the user focused questions — one round at a time, most load-bearing questions first.
2. Record every question, answer, and user-approved assumption in `.codex/dev-loop/clarification-log.md`.
3. Write the clarified goal and acceptance criteria into `source.md` (`## Goal`, `## Acceptance Criteria`).
4. Propose a task scale with a one-line reason (for example "single-file fix, no dependency changes: small") and confirm it with the user unless the user already chose one.

Advance only when the source is ready; the harness enforces non-empty Goal and Acceptance Criteria:

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

Planning review loop:

1. Spawn `plan-reviewer` with only source spec and planning artifacts.
2. Ask for `Decision: pass | needs-revision | block`.
3. Save the review under `.codex/dev-loop/reviews/plan-reviewer.md`.
4. Ensure the report includes `Agent ID:` and `Plan Fingerprint:` from the current harness state.
5. Record it with `scripts/dev_loop_harness.py record-review --role plan-reviewer --agent-id <subagent-id> --report <report.md>`.
6. If `needs-revision`, revise artifacts and re-review.
7. If `block`, stop with a blocker.
8. Continue only on `pass`.

Implementation review loop:

1. After implementation, spec merge, and unit verification, spawn `implementation-reviewer`.
2. Give it source spec, planning artifacts, git diff (including spec baseline changes), and test evidence.
3. Save output to `.codex/quality-gate/subagent-alignment.md`.
4. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, and `Workspace Fingerprint:`.
5. Also record it with `scripts/dev_loop_harness.py record-review --role implementation-reviewer --agent-id <subagent-id> --report <report.md>`.
6. Continue only if the report says `Decision: pass`.

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
2. Run the red stage and record the failing evidence:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-test --unit dev-001 --stage red --command "<test command>"
```

3. Implement until the test passes, then record the green stage (the harness refuses green without red evidence):

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-test --unit dev-001 --command "<test command>"
```

4. Refactor with the test green; re-run the green gate after refactors.

A red run that unexpectedly passes proves nothing: strengthen the test or re-plan the unit. `regression-only` units skip the red stage but still need their green gate.

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

Worktree evidence is interim by design: its workspace fingerprint does not match the merged main tree, so the final gate forces re-verification.

Finishing the implementation phase, in this order:

1. All units implemented and merged into the loop branch.
2. Merge the spec delta into the spec baseline and record it (next section).
3. Re-verify every unit against the final tree:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop verify-units
```

Rules:

- Retry a failing green gate only up to the configured retry limit; the counter tracks consecutive failures (red runs excluded) and resets on a pass.
- Do not advance beyond implementation until every `## Unit dev-*` has red evidence (or an approved waiver) and a current green pass.
- After the configured retry limit is exceeded, stop with a blocker.
- Record command, result, timestamp, and log path for every attempt.
- Do not skip tests or mark a failing unit complete.

## Spec Baseline Merge

Read [spec-baseline.md](references/spec-baseline.md) for the delta format and merge rules.

The repository keeps living specs under `<spec_dir>/` (default `specs/`), one file per capability. During implementation, after the code lands:

1. Apply `spec-delta.md` to the baseline: add, update, or delete the `#### Requirement:` blocks in `specs/<capability>.md` (create the file for a new capability).
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

- Requirements stay unclear after clarification rounds, or the user is unavailable to answer a load-bearing question.
- Plan review returns `block`.
- Test gate exceeds the configured retry limit with consecutive failures on the same unit.
- A red-stage test cannot be made to fail (the planned behavior may already exist or the unit is mis-scoped).
- The spec baseline cannot be reconciled with the reviewed spec delta.
- `$ai-code-quality-gate` fails.
- Subagent alignment returns anything other than `Decision: pass`.
- Risk review finds architecture, security, data, migration, compatibility, or external-service risk that needs a user decision.
- Required external credentials or tokens are missing.
- A non-GitHub external service would be called without user approval.
- Git branch, commit, push, or PR creation cannot complete.
- GitHub Actions required checks are absent, fail, or need missing secrets.
