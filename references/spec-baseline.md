# Spec Baseline

The repository keeps living, capability-scoped specifications under `<spec_dir>/` (default `specs/`, configurable via `spec_dir`). Each loop describes its requirement-level changes in `.codex/dev-loop/spec-delta.md`; after implementation, the delta is merged into the baseline on the same branch, so requirement changes are reviewed and shipped with the code — and the baseline stays current after every merge.

## Baseline File Format

One file per capability: `specs/<capability>.md`, kebab-case name.

```markdown
# <capability> Specification

Short purpose statement.

#### Requirement: <title>

Normative description. Use SHALL/MUST language for the binding parts.

- Acceptance: how this requirement is verified.

#### Requirement: <next title>

...
```

`#### Requirement: <title>` headings are the merge anchors; keep titles stable and unique within a file.

## Spec Delta Format

```markdown
# Spec Delta

## Capability: <kebab-name>

### ADDED Requirements

#### Requirement: <title>

<full requirement text as it should appear in the baseline>

### MODIFIED Requirements

#### Requirement: <existing title>

<full replacement text>

### REMOVED Requirements

#### Requirement: <existing title>

## No Spec Impact

<only when the change alters no requirement: one honest sentence why (pure refactor, tooling, docs, ...)>
```

Rules:

- Declare capability changes or a no-impact reason — never both, never neither. The harness rejects ambiguous or empty deltas.
- The delta is a planning artifact: plan review approves it, and editing it later invalidates reviews by fingerprint. Scope discovered during implementation means updating the delta and re-running plan review.
- Repeat `## Capability:` sections for multi-capability changes.

## Merge Procedure (implementation phase, after code lands)

1. Edit `specs/<capability>.md` for each declared capability:
   - ADDED: insert the requirement block. Create the file (with the `# <capability> Specification` header) for a new capability.
   - MODIFIED: replace the existing block under the same title.
   - REMOVED: delete the block.
2. Validate and record:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop record-spec-merge
```

The harness verifies mechanically: every normalized ADDED/MODIFIED requirement block exactly matches the capability file, duplicate titles are rejected, every REMOVED title is gone, and the result is bound to plan and workspace fingerprints. `## No Spec Impact` deltas are recorded without file checks.

3. Run `verify-units` afterwards — spec edits change the workspace fingerprint, so unit evidence must be refreshed against the final tree.

Implementation review and every later phase require a current recorded spec merge. Any subsequent code or spec edit stales the record; re-run `record-spec-merge` (and `verify-units`) after fixes.

## Ordering Inside The Implementation Phase

```text
implement units -> merge unit branches -> edit spec baseline -> record-spec-merge -> verify-units -> implementation_review
```

This order exists because every recorded evidence binds to the workspace fingerprint of the final tree.

## Review Expectations

- plan-reviewer: does the delta match the goal and acceptance criteria? Are ADDED/MODIFIED/REMOVED requirements complete and testable? Is a `No Spec Impact` claim actually true?
- implementation-reviewer: does the diff (including `specs/`) implement exactly the reviewed delta — no undeclared requirement drift?
