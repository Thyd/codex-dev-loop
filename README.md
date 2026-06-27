# Codex Dev Loop

Unofficial community skill for Codex. This project is not affiliated with, sponsored by, or endorsed by OpenAI.

`codex-dev-loop` is a guarded autonomous development loop for taking a Notion page or local Markdown spec from goal and acceptance criteria to reviewed code, tests, quality gates, a git branch, a pull request, and GitHub Actions verification.

## Features

- Intake from a local Markdown spec or a Notion page copied into `.codex/dev-loop/source.md`.
- Planning artifacts before coding:
  - technical design
  - file and module scope
  - test plan
  - risk analysis
  - unit-by-unit development plan
- Three-reviewer Subagent loop:
  - `plan-reviewer`
  - `implementation-reviewer`
  - `risk-reviewer`
- Fingerprint checks to prevent stale plans, tests, reviews, quality reports, PR records, or cloud-check records from being reused after changes.
- Forced unit test execution through `automated-dev-executor`.
- Required local quality gate through `ai-code-quality-gate`.
- Git branch, commit, push, PR, and GitHub Actions stages.
- GitHub PR-level review check requirement for Qodo PR-Agent, CodeRabbit, or another configured AI review check.
- Fail-closed blockers for unclear requirements, repeated test failures, quality failures, architecture/security/data risk, missing tokens, and failed or missing cloud checks.

## Repository Layout

```text
codex-dev-loop/
  SKILL.md
  agents/openai.yaml
  scripts/
    dev_loop_harness.py
    self_test.py
    validate_dev_loop_artifacts.py
  references/
    artifact-templates.md
    git-pr-flow.md
    github-actions-cloud.md
    subagent-review-loop.md
  docs/sponsor.md
  assets/wechat-pay-qr.jpg
```

## Installation

Clone this repository and copy the skill folder into your Codex skills directory:

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git
Copy-Item -Recurse -Force .\codex-dev-loop "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

Restart Codex after installation so it can discover the new skill.

The harness intentionally expects companion skills under:

```text
~/.codex/skills/automated-dev-executor
~/.codex/skills/ai-code-quality-gate
```

This fixed lookup is deliberate: the quality gate should not be replaceable by a task-local fake script.

## Dependencies

Required:

- Codex with local skill support.
- Python 3.10 or newer.
- Git.
- GitHub CLI `gh`, authenticated with access to the target repository.
- Installed companion skills:
  - `automated-dev-executor`
  - `ai-code-quality-gate`

Required for full PR/cloud enforcement:

- GitHub repository with push access.
- GitHub Actions enabled.
- `gh pr view` and `gh pr checks` access.

Optional, depending on repository configuration:

- Semgrep CLI.
- CodeQL CLI or GitHub CodeQL workflow.
- SonarQube or SonarCloud configuration.
- Qodana CLI or Qodana workflow.
- Qodo PR-Agent or CodeRabbit as PR-level review tooling.
- Notion connector, when the source spec is a Notion page.

## Basic Usage

Prepare a source spec with at least:

```markdown
## Goal

...

## Acceptance Criteria

- ...
```

Initialize loop state:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop init --source path/to/source.md
```

Create or update the required planning artifacts:

```text
.codex/dev-loop/technical-design.md
.codex/dev-loop/test-plan.md
.codex/dev-loop/risk-analysis.md
.codex/dev-loop/development-plan.md
.codex/dev-loop/decision-log.md
```

Capture fingerprints before asking Subagents to review:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop fingerprint
```

Move through phases only with the harness:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop set-phase plan_review
```

Run a unit test gate:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop run-test --unit dev-001 --command "npm test"
```

Run the local quality gate:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop run-quality
```

The normal workflow is best triggered by asking Codex to use `$codex-dev-loop` on a Notion page or Markdown spec.

## Permissions

The loop may need these permissions:

- Read the source Markdown file or Notion page content.
- Write local execution records under `.codex/dev-loop/`.
- Write local quality/test artifacts under `.codex/`.
- Create a new git branch.
- Commit local changes.
- Push to GitHub.
- Create or update a GitHub pull request.
- Query GitHub Actions checks through `gh`.
- Install local project dependencies required by tests or configured local gates.

The loop should stop and ask before:

- Enabling or calling non-GitHub external hosted services that are not already configured.
- Using paid scanner services.
- Using missing tokens or secrets.
- Accepting architecture, security, migration, data-loss, or compatibility risk outside the approved scope.

## Quality And Safety Model

This skill is designed to fail closed:

- Requirements without a goal and acceptance criteria are blocked.
- Planning artifacts must be reviewed before implementation.
- Every planned unit must have the latest test status `passed`.
- Tests are limited to three failed attempts per unit.
- Reviews and tests are bound to plan/workspace fingerprints.
- `run-quality` calls the installed `ai-code-quality-gate` script directly and refuses stale output directories.
- PR and GitHub Actions evidence is verified through GitHub CLI in normal use.

## Third-Party Tools And References

This repository does not vendor or redistribute the following tools. It coordinates or references them when they are installed or configured by the user:

- OpenAI Codex and Codex skills.
- GitHub, GitHub CLI, and GitHub Actions.
- Notion, when used as a spec source.
- Semgrep.
- GitHub CodeQL.
- SonarQube or SonarCloud.
- JetBrains Qodana.
- Qodo PR-Agent.
- CodeRabbit.

All product names, trademarks, and logos belong to their respective owners. Mentioning them here does not imply endorsement or affiliation.

## Sponsorship

If this skill helps your workflow, sponsorship supports maintenance, examples, documentation, and compatibility updates.

See [Sponsor this project](docs/sponsor.md).

The WeChat Pay QR image in `assets/wechat-pay-qr.jpg` is a maintainer-provided sponsorship asset. It is not licensed for reuse outside displaying sponsorship information for this repository.

## License

Code and documentation are released under the MIT License, except where noted for sponsorship assets.
