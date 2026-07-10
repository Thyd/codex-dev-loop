# GitHub Actions Cloud Stage

Use this after pushing the branch and opening a PR.

## Purpose

Local Codex execution is the development harness. GitHub Actions is the cloud enforcement layer.

The PR should not be considered complete until required GitHub checks are visible and pass. Missing configuration is a blocker, not a pass.

## Required Checks By Profile

Light and standard require:

- `ai-quality-gate`

Strict additionally requires:

- `semgrep`
- `codeql`
- `sonar`
- `qodana`
- `subagent-alignment`
- Qodo PR-Agent or CodeRabbit

Existing repository checks must still be respected, but an optional check is not promoted to a profile requirement merely because it exists. If a profile-required workflow/check is absent, add it within approved scope or stop with a blocker. Use the `$ai-code-quality-gate` GitHub Actions reference for the workflow body.

## Cloud Check Loop

After opening the PR:

1. Fetch PR check status with GitHub tooling or `gh`.
2. Record status under `.codex/dev-loop/github-actions.md`.
3. Record the result with `scripts/dev_loop_harness.py record-cloud --status passed` only when required checks pass.
5. If required checks are absent, add or update the workflow in the branch when it is inside the approved repo scope.
6. If checks fail because of code, fix code locally and repeat the development loop.
7. If checks fail because of missing secrets, missing paid service setup, branch protection, or organization settings, stop and ask the user.

The harness verifies cloud checks with `gh pr checks`. Strict requires Qodo PR-Agent, CodeRabbit, or another AI review check; standard does not require an external AI SaaS. Required check names are matched by exact canonical name or documented scanner alias, not arbitrary substring. Optional non-required checks may be recorded without blocking the loop. Do not hand-write cloud evidence during a real loop.

## Stop Conditions

Stop when:

- GitHub auth is missing.
- Required checks are pending beyond the practical session window.
- A cloud scanner needs a token that is not configured.
- A non-GitHub external service must be enabled.
- The PR cannot be opened or updated.

## Record Format

Write:

```markdown
# GitHub Actions

## PR

- URL:

## Checks

| Check | Status | URL |
| --- | --- | --- |

## Decision

pass | blocked

## Notes
```
