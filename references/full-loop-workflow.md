# Full Loop Workflow

## Contents

- [Preflight and configuration](#preflight-and-configuration)
- [Intake and requirements gate](#intake-and-requirements-gate)
- [Scale and planning](#scale-and-planning)
- [Adaptive validation scope](#adaptive-validation-scope)
- [Implementation and TDD](#implementation-and-tdd)
- [Spec, review, and quality](#spec-review-and-quality)
- [Git, PR, and cloud checks](#git-pr-and-cloud-checks)
- [Backtracking and archive](#backtracking-and-archive)
- [External services and stop conditions](#external-services-and-stop-conditions)

## Preflight And Configuration

Use `<loop-home>/config/codex-dev-loop.json` when present. `<loop-home>` is
`~/.codex` unless `CODEX_DEV_LOOP_HOME` relocates it. If configuration is
missing, run `scripts/configure_dev_loop.py`; it asks only for automation
level, source types, quality profile, and test retry limit. Advanced budget,
scale, spec-dir, and gate-script settings retain safe defaults.

Before resuming evidence created by an older core, inspect it:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop --workspace . doctor
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop --workspace . migrate-evidence --dry-run
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop --workspace . migrate-evidence
```

Read [evidence-contracts.md](evidence-contracts.md) before migrating or when
automation consumes JSON output. Resume an active state instead of re-running
`init`; archive a completed run before initializing the next one.

## Intake And Requirements Gate

Copy a Markdown or authorized Notion source into the loop. For a rough idea,
start with `--draft`:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop init \
  --source <source.md> --source-type markdown --scale <small|standard|large>
```

Record questions, answers, and approved assumptions in
`clarification-log.md`. Keep clarifying until `source.md` has a non-empty Goal
and Acceptance Criteria whose conditions, action, observable result, failure
condition, boundaries, and non-goals can map to tests.

Capture fingerprints, run a fresh `requirements-reviewer`, save its report,
and record it:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop fingerprint
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  record-review --role requirements-reviewer --agent-id <id> --report <report.md>
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop set-phase planning
```

Give the reviewer only the source, clarification log, and current source
fingerprint. Do not let it invent missing requirements.

## Scale And Planning

Confirm `small`, `standard`, or `large` with a one-line rationale. Raise scale
at any phase; lower it only in intake/planning. Never use `small` when the
change touches dependencies, migrations, SQL, CI/CD, Docker, Terraform,
credentials, or auth/security/secrets/crypto paths.

Create all planning artifacts from [artifact-templates.md](artifact-templates.md):
technical design, test plan, risk analysis, development plan, spec delta, and
decision log. Declare expected file scope and split work into independently
testable `dev-*` units with dependencies and one of:

- `TDD: red` — record a valid failing test before green.
- `TDD: regression-only` — no new executable behavior; existing tests or a
  direct artifact/contract check cover the change. Justify it in the reviewed
  plan.

Run a fresh `plan-reviewer` using the inputs and schema in
[subagent-review-loop.md](subagent-review-loop.md). Any planning-artifact edit
invalidates the review fingerprint and requires another review.

## Adaptive Validation Scope

Read [validation-selection.md](validation-selection.md). Choose `artifact`,
`targeted`, `impacted`, or `full` independently of task scale and record the
rationale, acceptance-criteria mapping, exact commands, and full-suite
omissions in `test-plan.md`. A small task can still require `full` because it
touches a sensitive shared surface; a standard task can use `impacted` when its
dependency reach is well bounded.

Use the narrowest credible command for each unit. Escalate when the diff grows,
shared consumers appear, or failures escape the planned surface. Never run a
full suite merely because it exists, and never skip all verification because a
change is lightweight.

## Implementation And TDD

Create and record a feature branch before implementation. Follow
[tdd-parallel-units.md](tdd-parallel-units.md).

For a red-mode unit:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-test \
  --unit dev-001 --stage red --expected-failure "<missing behavior>" \
  --command "<test command>"
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop run-test \
  --unit dev-001 --command "<test command>"
```

The red failure must prove the intended missing behavior, not import, syntax,
dependency, path, environment, or ambiguous snapshot failure. After green,
refactor and run green again. The harness applies scope and budget checks.

Work serially unless units are truly independent. Parallel units use isolated
git worktrees and fresh `unit-implementer` agents. Agents run tests and commit
inside their worktrees but never write shared loop state; the orchestrator
records returned red/green metadata serially. After merging, record a current
`merge-integrator` pass before `verify-units`.

## Spec Review And Quality

Apply `spec-delta.md` to the living baseline described by
[spec-baseline.md](spec-baseline.md), then record it:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-spec-merge
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop verify-units
```

Even `## No Spec Impact` must be justified and recorded. Run final-tree tests,
then fresh `implementation-reviewer`, `docs-impact-reviewer`, and required
`risk-reviewer` passes. Save implementation alignment under
`.codex/quality-gate/subagent-alignment.md`.

Run the configured quality gate; requirements are additive and cannot be
weakened at the command line. When the reviewed scope is below `full`, override
the fallback's repository-wide test autodetection with the selected final-tree
command:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  run-quality --command "test=<selected final-tree verification command>"
```

Use the companion quality skill when installed; otherwise the bundled fallback
enforces local gates. Stop on any required failure.

## Git PR And Cloud Checks

Read [git-pr-flow.md](git-pr-flow.md) before changing git state and
[github-actions-cloud.md](github-actions-cloud.md) after opening the PR.
Never commit directly to a protected branch. Commit only after current tests,
spec merge, reviews, and quality evidence pass.

Record a commit for `commit_only`; for full automation, push the feature branch,
open a PR, verify it belongs to the local `origin`, then record PR and required
cloud checks:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-commit
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-pr \
  --branch <branch> --commit <sha> --pr-url <url>
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-cloud \
  --status passed
```

Local PR/cloud simulation flags are self-test only and require
`CODEX_DEV_LOOP_TEST_MODE=1`.

## Backtracking And Archive

Move phases only through `set-phase`. Resolve a recorded blocker before
backtracking:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  resolve-blocker --reason "<what was fixed>"
```

Backtracking clears downstream evidence that could otherwise become stale.
Repeat affected tests, reviews, spec merge, quality, and delivery gates.

At completion, write the final report and known follow-ups, then archive:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop archive
```

The run moves under `.codex/dev-loop-archive/`; the repository `specs/`
baseline remains in place.

## External Services And Stop Conditions

Project dependency installation, GitHub/`gh`, and authorized source-Notion
reads are normal in-scope operations. Obtain explicit confirmation before
using an unconfigured hosted scanner, paid service, telemetry endpoint,
third-party AI review SaaS, or non-GitHub external API.

Stop with a decision brief when requirements remain ambiguous, a required
review does not pass, a red test cannot prove missing behavior, retry or budget
limits are reached, scope/spec reconciliation fails, architecture/security/
data/compatibility risk needs a human decision, credentials are missing, a
quality gate fails, or git/PR/cloud evidence cannot be completed.
