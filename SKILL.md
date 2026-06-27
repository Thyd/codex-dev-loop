---
name: codex-dev-loop
description: Run an end-to-end Codex autonomous development loop from a Notion page or local Markdown spec to reviewed implementation, tests, ai-code-quality-gate, git commit, pushed branch, and pull request. Use when Codex must elaborate a goal and acceptance criteria into technical design, file scope, test plan, risk analysis, development plan, Subagent reviews, implementation loops, quality gates, execution records, and GitHub PRs while stopping on ambiguity, repeated test failures, quality failures, architecture risk, or missing credentials.
---

# Codex Dev Loop

Current version: 0.2.2

## Operating Contract

Use this skill to drive a full local Codex harness plus GitHub Actions loop.

- Load first-run preferences from `~/.codex/config/codex-dev-loop.json` when present; otherwise use the default profile.
- Accept inputs from a Notion page or local Markdown spec.
- Start when the input has a goal and acceptance criteria.
- Produce technical design, file scope, test plan, risk analysis, and development plan before coding.
- Run Subagent review loops until planning artifacts pass.
- Implement one independently testable unit at a time.
- Force tests through a hook or explicit gate, stopping at the configured failure limit.
- Require `$ai-code-quality-gate` before commit, using the configured quality profile.
- Create a new git branch, commit changes, push, and open a PR unless the configured automation level stops earlier.
- Inspect GitHub Actions required checks after opening the PR when GitHub access is available.
- Write execution records, review reports, quality summaries, and PR description artifacts.
- Stop instead of guessing when requirements are unclear, architecture risk appears, external tokens are needed, or quality gates fail.

## Required Skills And Tools

- Use `$automated-dev-executor` for unit-by-unit implementation and forced test gates.
- Use `$ai-code-quality-gate` for the configured lint, typecheck, test, Semgrep, CodeQL, Sonar, Qodana, Subagent alignment, and AI PR review gates.
- Use `scripts/dev_loop_harness.py` as the local state ledger for phases, reviews, test attempts, quality gate, and PR records.
- Use `scripts/configure_dev_loop.py` to create or update first-run preferences.
- Use `multi_agent_v1` Subagents. If Subagents are unavailable, stop before planning review:
  - `plan-reviewer`
  - `implementation-reviewer`
  - `risk-reviewer`
- Use GitHub tooling or `gh` for pushing branches and opening PRs.
- Use Notion tools only when the input is a Notion page and the user has provided access.

## First-Run Configuration

Before the first full run, check whether this file exists:

```text
~/.codex/config/codex-dev-loop.json
```

If it is missing, ask the user to answer only these five setup questions, or run:

```bash
python <skill-dir>/scripts/configure_dev_loop.py
```

The five questions are:

1. Automation level: `pr_without_merge` (default), `commit_only`, or `planning_only`.
2. Source types: `markdown + notion` (default), `markdown`, or `notion`.
3. Quality profile: `standard` (default), `strict`, or `light`.
4. Test failure limit: `3` (default), `2`, `1`, or `0` for stop on first failure.
5. Risk mode: `stop_and_ask` (default), `serious_only`, or `best_effort`.

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
  "risk_mode": "stop_and_ask"
}
```

## Loop Overview

1. Intake the source spec.
2. Normalize it into a local execution record.
3. Generate planning artifacts.
4. Run plan Subagent review.
5. Revise planning artifacts until review passes.
6. Create a new branch.
7. Implement one unit at a time with test gates.
8. Run implementation Subagent alignment review.
9. Run risk Subagent review.
10. Run `$ai-code-quality-gate`.
11. Commit, push, and open a PR.
12. Inspect GitHub Actions required checks when GitHub access is available.
13. Write back records and final status.

## Intake

For local Markdown, read the file directly.

For Notion, fetch the page content and save a local copy under:

```text
.codex/dev-loop/source.md
```

The source must contain at least:

- Goal.
- Acceptance criteria.

If either is missing, stop with a blocker and ask the user for the missing information.

Initialize local loop state before generating planning artifacts:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop init --source <source.md> --source-type markdown
```

Use `--source-type notion` when the source was fetched from Notion. The harness refuses source types that are disabled by first-run configuration.

Advance phases only through the harness:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop set-phase plan_review
```

The harness rejects illegal jumps such as `planning -> complete`.
When the loop backtracks to an earlier phase, the harness clears downstream test, review, quality, PR, and cloud-check state so stale passes cannot be reused.

Before asking Subagents to review current artifacts, capture evidence fingerprints:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop fingerprint
```

Review reports must echo these fingerprints so stale reports cannot be reused after plan or code changes.

## Planning Artifacts

Before coding, create or update these files:

```text
.codex/dev-loop/technical-design.md
.codex/dev-loop/test-plan.md
.codex/dev-loop/risk-analysis.md
.codex/dev-loop/development-plan.md
.codex/dev-loop/decision-log.md
```

Use [artifact-templates.md](references/artifact-templates.md) for required headings.

The planning artifacts must include:

- Technical design.
- Expected file/module scope.
- Test plan.
- Risk analysis.
- Development plan split into independently testable units.
- Required tools and credentials.
- External service calls with reasons.

Do not start coding until plan review passes.

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

1. After implementation and narrow tests, spawn `implementation-reviewer`.
2. Give it source spec, planning artifacts, git diff, and test evidence.
3. Save output to `.codex/quality-gate/subagent-alignment.md`.
4. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, and `Workspace Fingerprint:`.
5. Also record it with `scripts/dev_loop_harness.py record-review --role implementation-reviewer --agent-id <subagent-id> --report <report.md>`.
6. Continue only if the report says `Decision: pass`.

Risk review loop:

1. Spawn `risk-reviewer` after implementation alignment passes.
2. Give it risk analysis, git diff, dependency changes, migrations, and test evidence.
3. Ensure the report includes `Agent ID:`, `Plan Fingerprint:`, and `Workspace Fingerprint:`.
4. Save and record it with `scripts/dev_loop_harness.py record-review --role risk-reviewer --agent-id <subagent-id> --report <report.md>`.
5. If it finds architecture, data, security, or external-service risk, stop unless the issue can be fixed without changing scope.

## Development Loop

Use `$automated-dev-executor` for implementation:

- Work on exactly one unit from `.codex/dev-loop/development-plan.md`.
- Run the unit's forced test gate.
- Retry a failing test gate only up to the configured failure limit.
- Run and record every attempt with `scripts/dev_loop_harness.py run-test --unit <unit-id> --command "<test command>"`.
- Do not advance beyond implementation until every `## Unit dev-*` in the development plan has latest test status `passed`.
- After the configured failure limit is reached, stop with a blocker.
- Record command, result, timestamp, and log path.
- Do not skip tests or mark a failing unit complete.

## Quality Gate

After all implementation units pass:

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

The harness runs the equivalent quality gate command:

```bash
python ~/.codex/skills/ai-code-quality-gate/scripts/quality_gate.py \
  --workspace . \
  --require <extra-gates> \
  --alignment-report .codex/quality-gate/subagent-alignment.md
```

For `strict` profile the harness also passes `--strict`. Configured profile gates are always required; `run-quality --require` can only add gates, not replace or weaken the profile. The harness requires real `$ai-code-quality-gate` output and verifies that all gates required by the configured profile pass. PR-level AI review is enforced later in the cloud check stage for standard and strict profiles.

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

- Commit only after tests, Subagent reviews, and `$ai-code-quality-gate` pass.
- In `commit_only` automation, record the committed HEAD before completing:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-commit
```

- Push the branch and open a PR.
- Include design, tests, risk, quality gate summary, and Subagent review summary in the PR body.
- Inspect GitHub Actions checks when available and record the result.
- Record branch, commit, and PR URL with `scripts/dev_loop_harness.py record-pr`; the harness verifies them with `gh pr view` and checks that the PR repository matches local `origin`.
- Record cloud checks with `scripts/dev_loop_harness.py record-cloud --status passed`; the harness verifies them with `gh pr checks`, requires exact canonical names for required checks, and does not let unrelated optional failures block the loop.
- `record-pr --allow-local-simulation` and `record-cloud --allow-local-simulation` are self-test only and require `CODEX_DEV_LOOP_TEST_MODE=1`.

Stop if:

- The repository is not a git repo.
- The worktree has unrelated dirty changes that conflict with the task.
- GitHub auth is unavailable.
- Branch creation, push, or PR creation fails.
- Required GitHub Actions workflow or required checks are absent and cannot be added within the approved repo changes.

## Writeback

Always write local records under:

```text
.codex/dev-loop/
```

If the input came from Notion, write a concise final status back to the Notion page only when Notion tools are available and the user has authorized it.

Final records must include:

- Source spec copy.
- Technical design.
- Test plan.
- Risk analysis.
- Development plan.
- Subagent review outputs.
- Test evidence paths.
- Quality gate summary.
- GitHub Actions check summary.
- Commit hash.
- PR URL.
- Known follow-ups.

## Stop Conditions

Stop and report a blocker when:

- Requirements are unclear.
- Plan review returns `block`.
- Test gate reaches the configured failure limit for the same unit.
- `$ai-code-quality-gate` fails.
- Subagent alignment returns anything other than `Decision: pass`.
- Risk review finds architecture, security, data, migration, compatibility, or external-service risk that needs a user decision.
- Required external credentials or tokens are missing.
- A non-GitHub external service would be called without user approval.
- Git branch, commit, push, or PR creation cannot complete.
- GitHub Actions required checks are absent, fail, or need missing secrets.
