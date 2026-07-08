# Changelog

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



