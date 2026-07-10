---
name: codex-dev-loop
description: Run an end-to-end autonomous development loop on Claude Code from a Markdown spec, Notion page, or clarified conversation to reviewed implementation, TDD-gated tests, spec baseline updates, quality gates, git commit, pushed branch, and pull request. Use when the agent must clarify a goal and acceptance criteria, size the task (small/standard/large gates), elaborate technical design, test plan, risk analysis, spec delta, and development plan, run subagent reviews, implement units test-first (optionally in parallel git worktrees), merge spec deltas into the repository spec baseline, enforce quality gates, and open GitHub PRs while stopping on ambiguity, repeated test failures, quality failures, architecture risk, or missing credentials.
---

# Codex Dev Loop — Claude Code Adapter

Current version: 0.7.0

This adapter runs the same harness-enforced loop as the root [SKILL.md](../../SKILL.md), mapped to Claude Code. The state machine, gates, fingerprints, artifacts, and stop conditions are identical; only the agent-specific mechanics differ. Read the root SKILL.md sections for anything not restated here — this file only overrides what is Claude-specific. Before resuming 0.5.x evidence, run `doctor`; preview and run `migrate-evidence` when required.

## Installation

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.claude/codex-dev-loop-src
cp -R ~/.claude/codex-dev-loop-src ~/.claude/skills/codex-dev-loop
cp ~/.claude/codex-dev-loop-src/adapters/claude-code/SKILL.md ~/.claude/skills/codex-dev-loop/SKILL.md
```

Keep the source clone clean. After every `git pull` in `~/.claude/codex-dev-loop-src`, replace the installed copy and re-apply the adapter; do not overwrite the tracked root `SKILL.md` inside the source clone.

## Claude Code Mapping

| Root SKILL.md says | On Claude Code do |
| --- | --- |
| `<loop-home>` = `~/.codex` | Set `CODEX_DEV_LOOP_HOME` to your `~/.claude` directory before every harness call, or export it for the session. Config then lives at `~/.claude/config/codex-dev-loop.json`. |
| Host subagent/collaboration API | Spawn each reviewer / unit-implementer with the Agent tool (`subagent_type: general-purpose`), one fresh agent per role per round. Use the returned agent/session id as `--agent-id`; never invent or pad an identifier. |
| `$automated-dev-executor` test gate | Not required. The harness auto-falls back to the bundled `<skill-dir>/scripts/test_gate.py` (same evidence protocol). |
| `$ai-code-quality-gate` | Not required. The harness auto-falls back to the bundled `<skill-dir>/scripts/quality_gate_fallback.py`. Pass explicit `--command "gate=<cmd>"` overrides to `run-quality` for gates the fallback cannot autodetect. |
| `$codex-dev-loop` invocation | The skill triggers via Claude Code's skill mechanism; the user may also invoke it as `/codex-dev-loop`. |

Everything else — phases, `init --draft` clarification, task scale and the sensitive-path guard, TDD red/green stages, `record-test` for worktrees, `merge-integrator` before `verify-units`, `record-spec-merge`, `docs-impact-reviewer` before quality, review fingerprints, budget/time-box limits, quality profiles, git/PR flow, `resolve-blocker`, `archive` — is unchanged; run the same `scripts/dev_loop_harness.py` commands with `<skill-dir>` = `~/.claude/skills/codex-dev-loop`.

Example first call:

```bash
CODEX_DEV_LOOP_HOME=~/.claude python ~/.claude/skills/codex-dev-loop/scripts/dev_loop_harness.py \
  --root .codex/dev-loop init --draft --scale small
```

(The `.codex/dev-loop` record directory name is part of the harness contract and stays the same on every agent.)

## Subagent Prompts

Use the prompt shapes from [subagent-review-loop.md](../../references/subagent-review-loop.md) and [tdd-parallel-units.md](../../references/tdd-parallel-units.md) verbatim inside the Agent tool prompt. Give each reviewer only its declared inputs (raw artifacts, diff, evidence) — not your conclusions. For parallel units, spawn one unit-implementer Agent per worktree (`run_in_background` is fine), but record all evidence yourself, serially, through the harness.

## Clarification On Claude Code

During the `intake` phase, ask the user clarification questions directly in chat (use the AskUserQuestion tool when available, one focused round at a time), record Q&A in `.codex/dev-loop/clarification-log.md`, run and record `requirements-reviewer` with the current `SOURCE_FINGERPRINT`, and only then `set-phase planning`. If the user is unavailable and a load-bearing question is open, stop with a blocker instead of guessing.

## Quality Gate Notes

- The bundled fallback autodetects `npm/pnpm/yarn` scripts, `pytest`, `go`, `cargo`, and `semgrep` on PATH; anything else needs a `--command "gate=<cmd>"` override.
- The `strict` profile expects hosted scanners (Sonar, Qodana, CodeQL) wired through GitHub Actions; on repos without them, use `standard` or `light` and say so in the PR body.
- External service policy is unchanged: ask the user before calling any non-GitHub hosted service.



