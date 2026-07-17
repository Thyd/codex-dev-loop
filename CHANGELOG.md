# Changelog

## 0.7.1 - 2026-07-17

### Added

- Added `references/validation-selection.md` with independent `artifact`, `targeted`, `impacted`, and `full` verification scopes.
- Added a lightweight asset lane for image, copy, documentation, fixture, and other non-executable changes, recording direct checks with `regression-only` evidence.

### Changed

- Made task scale control workflow weight while validation scope controls which commands run; full suites now require impact, risk, repository policy, release policy, or an explicit user requirement.
- Made unit and final-tree verification use the reviewed smallest credible command, and documented `run-quality --command "test=<command>"` as the way to prevent repository-wide test autodetection for bounded changes.
- Expanded `regression-only` semantics and shipping evidence to cover direct artifact or contract checks when no executable behavior is added.
- Made package frontmatter validation newline-agnostic so CRLF checkouts pass on Windows while BOM and required-field checks remain fail-closed.
- Made localized first-run summaries tolerate legacy Windows output encodings instead of aborting after writing the configuration file.

### Compatibility

- CLI paths, command names, phase semantics, evidence schema `1`, and config schema `4` remain unchanged. Existing 0.7.0 evidence remains readable.

## 0.7.0 - 2026-07-11

### Added

- Added a pinned pytest development environment, native pytest contract and integration suites, and subprocess-safe repository-local fixtures.
- Added Windows, Linux, and macOS CI across Python 3.11 and 3.13, with separate fast and slow pytest jobs inside each matrix entry.
- Added `scripts/forward_test.py` to prepare neutral planning-only and commit-only tasks for fresh agents and to evaluate raw archive, review, TDD, quality, Git, and automation-boundary evidence.

### Changed

- Reduced trigger-time `SKILL.md` from 490 lines to about 160 and moved the complete phase manual into `references/full-loop-workflow.md` with progressive-disclosure navigation.
- Split the 3,660-line harness implementation into focused settings, workspace, spec, validation, loop-command, standalone-command, parser, and compatibility-facade modules without changing the public CLI or legacy Python import surface.
- Split the legacy self-test implementation into native pytest loop and standalone integration suites; `self_test.py` and `legacy_self_test.py` are now thin compatibility runners.
- Made successful archive removal part of the explicit completion contract after a real forward test found that `phase: complete` alone was too easy to report as finished.

### Compatibility

- CLI paths, command names, phase semantics, evidence schema `1`, and config schema `4` remain unchanged. Existing 0.6.x evidence remains readable.

## 0.6.0 - 2026-07-10

### Added

- Added evidence schema v1 for loop state and standalone TDD/review ledgers. Legacy 0.5.x documents migrate without losing unknown host fields; corrupt, wrong-kind, and future-schema documents fail closed.
- Added read-only `doctor` and explicit `migrate-evidence` commands, including dry-run and stable JSON output. `version --json` and `fingerprint --json` expose machine-readable contracts for adapters and automation.
- Added focused contract, CLI compatibility, evidence integration, and test-layout suites.

### Changed

- Turned `scripts/dev_loop_harness.py` into a stable thin entrypoint backed by the modular `scripts/dev_loop_core/` package while preserving every existing command and Python import used by bundled tooling.
- Centralized atomic evidence persistence in the core contract layer. Existing mutating commands rewrite legacy evidence to the current schema on their next successful write.
- Replaced the monolithic self-test entrypoint with a focused suite runner. Legacy loop and standalone integration scenarios now use repository-local, subprocess-safe sandboxes and run independently in CI on Windows and Linux.

### Compatibility

- Existing CLI paths, command names, phase semantics, and 0.5.x evidence remain supported. Run `doctor`, then preview and apply `migrate-evidence` before resuming an in-flight 0.5.x workspace.

## 0.5.2 - 2026-07-10

### Fixed

- Removed UTF-8 BOMs from packaged skill entrypoints so YAML frontmatter starts at byte zero; added `validate_skill_package.py` and a Windows/Linux CI matrix to prevent discovery regressions and version drift.
- Replaced the stale `multi_agent_v1` instruction with host-capability-based subagent spawning and aligned the Claude adapter, core, package, and UI metadata on version 0.5.2.
- Bound requirements review fingerprints to both `source.md` and `clarification-log.md`.
- Made large-scale artifact validation require content in every declared design, test, and risk section; reviewer reports now require non-empty evidence sections.
- Required a declared expected failure for red-stage evidence and added Unicode-aware failure matching.
- Upgraded spec reconciliation from title presence to normalized requirement-block equality, with duplicate-title and strict kebab-case capability checks.
- Added a `plan-only` artifact-validation profile; reordered standalone shipping around feature-branch creation; made `ship-check` require every declared behavior label on the final tree; and enforced sensitive-path escalation inside standalone TDD and shipping.
- Made final review validation honor the small-scale risk-review skip and counted untracked source content in `max_diff_lines`.

### Changed

- Config schema v4 removes the non-functional `risk_mode` preference. Architecture, security, data, credentials, external services, and required quality gates remain unconditional hard stops.
- Standard cloud checks no longer require a third-party AI review SaaS; strict still requires the configured scanners and PR AI review.
- Added Chinese `## 目标` / `## 验收标准` aliases, core-version handshakes for every copied sub-skill, and explicit `dev-debug` routing.
- Reduced the trigger-time root `SKILL.md` below 500 lines by making the reviewer reference canonical, and added a contents section to the long reviewer reference.

## 0.5.1 - 2026-07-08

### Added

- Added schema v3 budget/time-box hooks: `max_units`, `max_files_changed`, `max_test_retries_per_unit`, `max_review_iterations`, `max_quality_fix_rounds`, and `max_diff_lines`; reaching a limit records a blocker and stops instead of continuing to expand scope or iterate.
- Added `docs-impact-reviewer` before the quality gate; it checks whether README, docs/, API reference, changelog, examples, env/config docs, migration notes, or user-facing copy need updates, and blocks quality until the current workspace records `Decision: no-docs-needed`.
- Added `merge-integrator` for parallel worktree merges; when worktree test evidence exists, `verify-units` is blocked until a current merge-integrator review checks cross-unit duplicate logic, shared-interface assumptions, test-order coupling, hidden route/config/export/schema/type conflicts, and integration-test needs.
- Added `scope-check` plus scope-drift hooks after unit green, worktree green records, before spec merge, and before the quality/commit path; the gate compares changed files to declared technical-design/development-plan scope and blocks undeclared files, sensitive paths, dependency manifests, and broad formatting noise.
- Added `validate-red` plus red-test-validator enforcement for `run-test --stage red`, `record-test --stage red`, and `standalone-test --stage red`; failed red runs now must fail for the intended reason, not import/syntax/dependency/path/environment errors or ambiguous snapshot drift.
- Intake now has a harness-enforced `requirements-reviewer` gate: `set-phase planning` requires non-empty Goal/Acceptance Criteria plus a current source-fingerprinted pass that checks observability, failure conditions, boundaries, non-goals, and test mapping.

## 0.5.0 - 2026-07-07

Composability release: the monolithic loop keeps its harness-enforced evidence chain, but each phase is now also an independently triggerable `dev-*` sub-skill for small tasks — "compose, but every segment leaves evidence." The loop state machine is unchanged.

### Added

- Composable standalone mode in the harness (loop code untouched): new commands `version` (`--require` handshake, `CORE_VERSION`), `guard-check` (exposes the sensitive-path detector for routing/tripwires), `check-spec` (Goal/Acceptance Criteria gate), `standalone-fingerprint`, `standalone-test` (red/green TDD with red-before-green, plus `--mode regression-only`; evidence in `<evidence_dir>/tdd/ledger.json`), `standalone-review` (bound to a target-file fingerprint), `check-spec-delta` (standalone spec-baseline validation), and `ship-check` (floor gate: git repo, non-protected branch, current green evidence).
- Single-source-of-truth guard: standalone write commands are refused while a loop is active (`loop-state.json` exists and phase != complete), so evidence cannot fork. Read-only helpers (`guard-check`, `check-spec`, `check-spec-delta`, `standalone-fingerprint`) always work.
- Seven `dev-*` sub-skills under `skills/`: `dev-clarify`, `dev-plan`, `dev-review`, `dev-tdd`, `dev-spec` (incl. brownfield baseline bootstrap), `dev-ship`, and `dev-debug` (systematic-debugging methodology). They are thin skins that call the shared harness — no gate logic of their own.
- `references/routing.md`: shared decision tree, escalation tripwires, floor-gate set, and single-source-of-truth rule that every skill points to.
- `adopt-evidence`: the upgrade path. When a standalone `dev-tdd` task grows into a full loop, this absorbs each standalone green whose workspace fingerprint still matches the current tree (re-stamping red-before-green evidence to the current plan) so verified units are not re-run.
- `scripts/install_skills.py`: install a selected subset (or all) of the sub-skills into `<home>/skills/` (`--home`, `--only`, `--list`, `--dry-run`; honors `CODEX_DEV_LOOP_HOME`).
- Config key `evidence_dir` (empty = auto; Codex hosts use `.codex/evidence/`, other hosts choose and persist a workspace-relative dir).
- Orchestrator SKILL.md "Composition" section mapping each loop phase to its canonical sub-skill methodology: methodology lives in the sub-skill, enforcement lives in the harness.

### Changed

- The loop's `record-spec-merge` and the new standalone `check-spec-delta` share one extracted validator (`spec_delta_baseline_problems`), so the mechanical baseline check cannot drift between them.
- `docs/composability-roadmap.md` records the confirmed design decisions and marks P1–P4 complete.

## 0.4.0 - 2026-07-07

### Added

- Clarification-first intake: `init` now starts every loop in the `intake` phase; `init --draft` starts from a skeleton `source.md` for rough ideas. `set-phase planning` is refused until Goal and Acceptance Criteria are non-empty; Q&A is recorded in the new `clarification-log.md` artifact, and `planning`/`plan_review` can backtrack to `intake` for re-clarification.
- TDD gates inside every development unit: `run-test --stage red` records failing red evidence (excluded from the failure limit; an unexpectedly passing red run is flagged); green runs are refused without current red evidence. Units may declare `- TDD: regression-only` in the development plan for refactors covered by existing tests — the waiver sits in the plan so plan review must approve it.
- Parallel unit development in isolated git worktrees: the new `record-test --unit --meta --worktree --stage` command records evidence produced by unit-implementer Subagents inside linked worktrees (non-worktree paths are rejected), and the new `verify-units` command re-runs every unit's green gate against the merged main tree. Worktree evidence is interim by design: its workspace fingerprint cannot satisfy the final gate.
- Spec baseline consolidation (OpenSpec-inspired): `spec-delta.md` is a new required planning artifact (capability requirement changes or a justified `## No Spec Impact`, never both). The new `record-spec-merge` command mechanically validates that `<spec_dir>/<capability>.md` files contain every ADDED/MODIFIED `#### Requirement:` title and none of the REMOVED ones; implementation review and all later phases are blocked until the recorded merge is current. Spec updates ride the same branch, diff, reviews, and PR as the code.
- Task-scale adaptive gates: `init --scale small|standard|large` (default from the new `default_scale` config key) plus a `set-scale` command (raising allowed anytime; lowering only during intake/planning). `small` relaxes planning-artifact content requirements and may skip the `risk_review` phase — but a hard sensitive-path guard refuses the skip whenever the change set touches dependency manifests, lockfiles, migrations, SQL, CI/CD, Docker, Terraform, keys, or auth/security/secrets paths. `large` requires every required artifact section to be filled.
- Bundled gate fallbacks: `scripts/test_gate.py` and `scripts/quality_gate_fallback.py` speak the same evidence protocols as the companion skills, so the loop runs without `automated-dev-executor` / `ai-code-quality-gate` installed. Resolution order: home-anchored config override, companion skill, bundled fallback.
- Claude Code adapter (`adapters/claude-code/SKILL.md`): same harness and gates, with subagents mapped to the Agent tool, `CODEX_DEV_LOOP_HOME=~/.claude`, and the bundled gate fallbacks.
- `CODEX_DEV_LOOP_HOME` environment variable relocates the loop home (config and companion-skill paths) for non-Codex agents.
- `archive` command (allowed at `complete`): moves the run's records to `.codex/dev-loop-archive/<timestamp>-<branch>/` so the next loop starts clean; `init` now refuses to overwrite an unarchived loop without `--force`.
- New references: `tdd-parallel-units.md` (TDD stages, worktree orchestration, unit-implementer prompt) and `spec-baseline.md` (baseline format, delta format, merge procedure).

### Changed

- Config schema v2: new keys `default_scale`, `spec_dir`, `test_gate_script`, `quality_gate_script`. Schema v1 configs migrate automatically with safe defaults; the wizard still asks only five questions. Gate-script overrides are honored only from the home-anchored config file so a workspace-local `--config` cannot swap in a fake gate.
- `spec-delta.md` joined the fingerprinted core planning artifacts: editing it after review invalidates reviews, exactly like editing the development plan.
- Backtracking now also clears stale spec-merge state; the unit-completion gate additionally requires the latest attempt to be a green-stage pass plus red evidence (or an approved waiver).
- The self-test now runs fully hermetic against the bundled gate fallbacks (no companion skills required) and covers intake clarification, TDD stages, worktree recording, verify-units, spec merge validation, scale guard and escalation rules, config migration, gate-script resolution priority, and archive.

### Fixed

- `resolve-blocker --reason` help text claimed the reason lands in `decision-log.md`; it is recorded in `blocker-resolutions.md` (writing to the decision log would invalidate the plan fingerprint as a side effect).
- `VERSION` still said `0.2.2` in the 0.3.0 release; version markers are now aligned.

## 0.3.0 - 2026-07-06

### Added

- `resolve-blocker --reason` harness command: blocked loops previously had no legal recovery path because every phase transition asserts no blockers exist; resolutions are appended to `blocker-resolutions.md` and kept in loop state for audit.
- Bash install and configuration commands in the README alongside the existing PowerShell commands.

### Changed

- `test_failure_limit` now means the number of automatic retries after a failure: `0` blocks on the first failure and `3` blocks on the fourth consecutive failure, matching the configuration wizard wording. The counter tracks consecutive failures, resets on a pass, and resets after `resolve-blocker`.
- Required GitHub Actions checks now also match known scanner aliases as hyphen-delimited tokens (`sonar`/`sonarcloud`/`sonarqube`, `qodana`, `codeql`, `semgrep`), so real-world check names such as `SonarCloud Code Analysis` satisfy the strict profile. Loop-owned checks such as `ai-quality-gate` still require an exact canonical match.
- `run-test` refuses to run while the loop is blocked.
- Loop state is written atomically (temp file + rename) so an interrupted command cannot corrupt `loop-state.json`.

### Fixed

- `gh` invocations no longer merge stderr into stdout; CLI notices and update hints previously could corrupt JSON parsing of `gh pr view` / `gh pr checks` output.
- Removed unused `REQUIRED_CLOUD_CHECKS` and `REQUIRED_QUALITY_GATES` constants that duplicated (and could drift from) the quality-profile definitions.


## 0.2.2 - 2026-06-27

### Fixed

- Made `run-quality --require` additive so callers cannot weaken the configured quality profile.
- Updated `validate_dev_loop_artifacts.py` to reuse harness validation semantics when loop state or final records are involved.
- Matched GitHub Actions required checks by exact canonical name instead of substring.
- Bound PR evidence to the local GitHub `origin` repository before accepting a recorded PR.

## 0.2.1 - 2026-06-27

### Fixed

- Restricted PR and GitHub Actions local simulation to self-test mode via `CODEX_DEV_LOOP_TEST_MODE=1`.
- Tightened GitHub Actions evidence validation so a plain `completed` state no longer counts as a passing check.
- Required PR evidence to reference an open PR instead of accepting merged PRs during the PR recording stage.
- Enforced configured source types during `init --source-type ...`.
- Added safe completion paths for `planning_only` and `commit_only` automation levels.
- Made final validation respect `planning_only`, `commit_only`, and full PR automation scopes.

### Added

- Added `record-commit` to bind commit-only completion to the current HEAD and workspace fingerprint.
- Added self-test coverage for source type enforcement, early completion modes, local simulation restrictions, and stricter cloud check states.
