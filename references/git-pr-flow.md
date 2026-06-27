# Git And PR Flow

Use this when the loop reaches branch, commit, push, and PR creation.

## Preflight

Run:

```bash
git status --short
git branch --show-current
git remote -v
```

Stop when:

- Not inside a git repository.
- Current branch is unclear.
- Remote is missing.
- Worktree has unrelated dirty changes that conflict with the task.

## Branch

Create a branch name from the source spec:

```text
codex/<short-topic>-YYYYMMDD-HHMM
```

Never commit directly to `main`, `master`, `develop`, or a protected release branch.

Record the branch in the harness before implementation:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-branch --branch <branch>
```

## Commit

Commit only after:

- Plan review passed.
- All development units passed their test gates.
- Implementation review passed.
- Risk review passed.
- `$ai-code-quality-gate` passed.
- Final report was written.

Commit message:

```text
<type>: <short summary>

Source: <Notion page or local markdown path>
Tests: <summary>
Quality: ai-code-quality-gate passed
```

## Push And PR

Use GitHub tooling or `gh`:

```bash
git push -u origin <branch>
gh pr create --title "<title>" --body-file .codex/dev-loop/pr-body.md
```

Record the PR:

```bash
python <skill-dir>/scripts/dev_loop_harness.py \
  --root .codex/dev-loop \
  record-pr \
  --branch <branch> \
  --commit <commit> \
  --pr-url <url>
```

The harness verifies PR URL, head branch, and head SHA with `gh pr view`. If GitHub authentication is missing, stop and ask for credentials.

## PR Body

Include:

- Source spec.
- Technical design summary.
- Implementation summary.
- Test evidence.
- Quality gate summary.
- Subagent review summary.
- Risk summary.
- Follow-ups.
