# Changelog

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
