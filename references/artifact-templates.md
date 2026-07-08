# Artifact Templates

Use these headings for `.codex/dev-loop/` records.

## clarification-log.md

```markdown
# Clarification Log

## Open Questions

## Answered

| Question | Answer | Source | Date |
| --- | --- | --- | --- |

## Assumptions Approved By User
```

## technical-design.md

```markdown
# Technical Design

## Goal

## Acceptance Criteria

## Proposed Approach

## File And Module Scope

## Data Model Or API Changes

## Dependencies

## Non-Goals

## Open Questions
```

## test-plan.md

```markdown
# Test Plan

## Unit Tests

## Integration Tests

## E2E Or Browser Tests

## Static Gates

## Manual Checks

## Coverage Gaps
```

## risk-analysis.md

```markdown
# Risk Analysis

## Correctness Risks

## Security Risks

## Data Or Migration Risks

## Architecture Risks

## Compatibility Risks

## External Service Or Credential Risks

## Mitigations
```

## development-plan.md

`- TDD:` is `red` (default, failing test required first) or `regression-only` (existing tests cover the change; justify it for plan review).

```markdown
# Development Plan

## Unit dev-001

- Objective:
- Scope:
- Acceptance:
- Test gate:
- TDD: red
- Dependencies:
- Status: pending
- Evidence:

## Unit dev-002

- Objective:
- Scope:
- Acceptance:
- Test gate:
- TDD: red
- Dependencies: dev-001
- Status: pending
- Evidence:
```

## spec-delta.md

Declare capability requirement changes or a justified no-impact — exactly one of the two. See [spec-baseline.md](spec-baseline.md).

```markdown
# Spec Delta

## Capability: <kebab-name>

### ADDED Requirements

#### Requirement: <title>

<requirement text>

### MODIFIED Requirements

### REMOVED Requirements

## No Spec Impact
```

## decision-log.md

```markdown
# Decision Log

## YYYY-MM-DD HH:MM

- Decision:
- Reason:
- Alternatives:
- Evidence:
```

## final-report.md

```markdown
# Final Report

## Summary

## Changed Files

## Test Evidence

## Quality Gate

## Subagent Reviews

## Commit

## Pull Request

## Follow-Ups
```

## pr-body.md

```markdown
## Summary

## Technical Design

## Tests

## Quality Gate

## Subagent Reviews

## Risk

## Follow-ups
```
