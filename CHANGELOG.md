# Changelog

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
