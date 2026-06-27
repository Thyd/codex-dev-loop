# GitHub Actions Cloud Stage

Use this after pushing the branch and opening a PR.

## Purpose

Local Codex execution is the development harness. GitHub Actions is the cloud enforcement layer.

The PR should not be considered complete until required GitHub checks are visible and pass. Missing configuration is a blocker, not a pass.

## Required Checks

Require these checks. If the repository does not have the workflow/checks, add the workflow as part of the branch or stop with a blocker:

- `ai-quality-gate`
- `semgrep`
- `codeql`
- `sonar`
- `qodana`
- `subagent-alignment`
- Qodo PR-Agent or CodeRabbit

Use the `$ai-code-quality-gate` GitHub Actions reference for the workflow body.

## Cloud Check Loop

After opening the PR:

1. Fetch PR check status with GitHub tooling or `gh`.
2. Record status under `.codex/dev-loop/github-actions.md`.
3. Record the result with `scripts/dev_loop_harness.py record-cloud --status passed` only when required checks pass.
5. If required checks are absent, add or update the workflow in the branch when it is inside the approved repo scope.
6. If checks fail because of code, fix code locally and repeat the development loop.
7. If checks fail because of missing secrets, missing paid service setup, branch protection, or organization settings, stop and ask the user.

The harness verifies cloud checks with `gh pr checks` and requires the fixed checks plus Qodo PR-Agent, CodeRabbit, or another AI review check. Required check names are matched by exact canonical name, not by substring. Optional non-required checks may be recorded, but they do not block the loop unless they are the required AI review check. Do not hand-write cloud evidence during a real loop.

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
