# GitHub Actions Cloud Stage

Use this after pushing the branch and opening a PR.

## Contents

- [Required checks](#required-checks)
- [Cloud check loop](#cloud-check-loop)
- [Quota policy](#quota-policy)
- [Standalone dev-ship](#standalone-dev-ship)
- [Stop conditions](#stop-conditions)
- [Record format](#record-format)

## Required Checks

Light and standard require `ai-quality-gate`. Strict additionally requires
`semgrep`, `codeql`, `sonar`, `qodana`, `subagent-alignment`, and Qodo PR-Agent or
CodeRabbit. The harness also fetches repository-required names for both normal
cloud results and quota handling. Use `--extra-required-check` for additional
project-policy requirements not configured in GitHub, and repeat those flags
when retrying or recording recovery.

An optional check is not promoted to a profile requirement merely because it
exists. If a profile-required check is absent, add it within approved scope or
stop. Use the `$ai-code-quality-gate` GitHub Actions reference for workflow setup.

## Cloud Check Loop

1. Fetch PR checks with `gh pr checks`, recording status in `github-actions.md`.
2. Run `record-cloud --status passed` only when required checks pass. The
   harness verifies live GitHub evidence; scanner aliases are supported, not
   arbitrary substrings.
3. For code failures, fix locally and repeat affected development gates.
4. For quota/billing failures, apply the saved policy below. Do not ask again.
5. Missing credentials, workflows, secrets, service setup, or permissions remain
   blockers; quota fallback does not apply to them.

## Quota Policy

First-run setup asks, in this order:

1. **降级为本地由当前 agent 补做测试** → `ci_quota_policy: local_fallback`.
2. **待用户付费后再按原计划继续** → `ci_quota_policy: wait_for_payment`.

Save the user's choice with `configure_dev_loop.py --non-interactive
--ci-quota-policy <choice>`. Existing settings survive; missing legacy choices
default to waiting until the user answers. `init` snapshots the preference;
resuming a run reuses it. Legacy active states missing the field adopt the
saved choice at their next `record-cloud` call.

When GitHub reports an account quota/billing restriction:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  record-cloud --status quota-exhausted
```

The harness verifies the PR still matches the local repository and commit,
fetches check runs and annotations, and requires explicit quota/billing
diagnostics for every nonpassing required check. A missing, pending, unrelated,
or code-failed check cannot be replaced under this policy. The original GitHub
response and annotations are retained. Do not infer exhausted quota from a
generic `failure`, timeout, API rate limit, or authentication error.

**If `local_fallback` was selected:** the command lists the blocked check names.
The current agent reads their workflow steps and maps each to equivalent local
commands, including any required build, test, lint, type, or scanner steps.
Run the actual checks; an echo command, status-summary script with invented
success inputs, or an earlier green run is not replacement evidence. Reuse
the saved policy without requesting fallback approval again. Document the
workflow-to-command mapping and environment differences in `github-actions.md`
after the harness writes its summary.

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  record-cloud --status quota-exhausted \
  --local-check "ai-quality-gate=<equivalent local verification command>" \
  --local-check "<another blocked required check>=<equivalent command>" \
  --timeout 900
```

Pass one `--local-check` per blocked check, using the exact returned name.
The harness executes each command locally and records commands, exit codes,
logs, timestamps, commit, plan/workspace fingerprints, and evidence hashes.
All must pass against unchanged inputs before `local_fallback_passed` can
satisfy completion and archive. `cloud_status` remains `quota-exhausted`.
An interrupted run, failed command, changed file/commit, or incomplete mapping
does not pass. If equivalent local checks are unavailable (such as a required
OS matrix or hosted-only scanner), report the gap and retain the blocker.
This policy does not reduce the quality profile or enable paid services.

After a local failure, fix its cause, resolve the blocker, and repeat affected
gates. Record fresh CI evidence on the new commit if the code changed. On a
local pass, continue to the configured completion point and archive; disclose
the local result and still-blocked cloud status in the PR and final report.
Do not rerun paid GitHub jobs under this option unless the user asks.

**If `wait_for_payment` was selected:** the command saves
`waiting_for_payment` and a blocker in `cloud_checks`, without executing local
commands. Report the payment/quota blocker and retain the run. Do not repeatedly
retry or request a different policy. After the user restores quota, rerun the
affected GitHub jobs and read their results; payment alone is not a CI pass.

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  resolve-blocker --reason "User restored GitHub quota; required jobs were rerun"
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  record-cloud --status passed
```

Both choices keep the original automation scope. They do not authorize merging,
changing branch protection, or marking blocked GitHub checks successful.
`planning_only` and `commit_only` never require this cloud-stage procedure.
Quota fallback uses live GitHub evidence; simulation flags cannot enable it.

## Standalone Dev-Ship

Read the same saved config and ask missing preferences through the setup wizard.
Without an active full loop, verify quota annotations and the PR commit as
above. For `local_fallback`, execute each equivalent command with
`standalone-test --label ci-<check> --mode regression-only --stage green
--command "<equivalent command>"`. Keep the GitHub quota evidence, mapping,
commit, and generated test logs with the standalone evidence; report local
success separately from cloud status. For `wait_for_payment`, retain evidence
and resume GitHub checks after quota restoration. Never create a fake full-loop
state to use `record-cloud`, or start standalone evidence during an active loop.

## Stop Conditions

Stop for missing GitHub auth, unavailable PR operations, absent required
checks, pending checks beyond the practical session window, or missing scanner
credentials. Enabling a non-GitHub external service still requires the user's
authorization. Stop on non-quota failures or incomplete local replacements.

## Record Format

`github-actions.md` should identify PR URL and commit, required check names and
links, original cloud status, quota diagnostics, saved policy, local command
mapping and logs if applicable, gaps, and the decision. Use `passed`,
`local_fallback_passed`, or a specific blocked/waiting outcome; never call a
local replacement a cloud pass.

API references: [GitHub CLI checks](https://cli.github.com/manual/gh_pr_checks)
and [check runs and annotations](https://docs.github.com/en/rest/checks/runs).
