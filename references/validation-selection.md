# Adaptive Validation Selection

Choose the smallest verification set that can credibly detect a regression from
the current change. Task scale controls workflow weight; validation scope
controls which commands run. Decide and record both separately.

## Selection Procedure

1. Inspect the changed file types, their consumers, declared acceptance
   criteria, repository test layout, and project-mandated checks.
2. Select one scope below and write its rationale and exact commands in
   `test-plan.md` before implementation.
3. Map every acceptance criterion to automated or manual evidence. Never use
   "no full suite" to mean "no verification."
4. Escalate the scope when the diff, dependencies, or observed failures show a
   wider impact than planned.

## Scopes

| Scope | Use when | Required evidence |
| --- | --- | --- |
| `artifact` | Bounded images, copy, docs, fixtures, or other non-executable assets with no code/config/interface change | Validate file integrity and the asset contract; resolve references; render, preview, or build only the affected surface when applicable |
| `targeted` | One behavior, component, module, or route with known direct tests | Run the narrowest tests for that behavior plus directly relevant lint/type/static checks |
| `impacted` | Several modules or a shared internal interface can affect known downstream consumers | Run targeted tests plus affected integration/consumer tests and a focused smoke check |
| `full` | Impact cannot be bounded safely or repository/release policy requires it | Run the complete relevant test and quality suites |

An image replacement normally uses `artifact`: confirm that the file decodes,
matches required format/dimensions/size or transparency constraints, all
references resolve, and the affected UI/build preview is valid. Do not run the
repository's code test suite unless the asset pipeline, generated output, or a
consumer contract makes it relevant.

For a standalone artifact lane, record the direct check without inventing a
failing red test:

```bash
python <core> standalone-test --label <asset-label> \
  --mode regression-only --stage green --command "<artifact check>"
```

## Full-Suite Triggers

Use `full` when any of these apply:

- dependency or lockfile, build system, framework, CI, runtime configuration,
  migration, schema, generated-code pipeline, or public API changes;
- auth, security, secrets, crypto, concurrency, persistence, or other
  sensitive behavior;
- broad refactors, shared-core changes, many downstream consumers, or unclear
  dependency reach;
- targeted/impacted checks fail outside the expected surface;
- the user, repository policy, release process, or required CI explicitly
  demands the full suite.

If test selection is uncertain after inspecting the repository, escalate one
level; use `full` only when the uncertainty cannot be bounded.

## Loop And Quality Commands

Use the selected command for each unit's red/green evidence. `verify-units`
then repeats those commands against the final tree; it does not require every
unit to use the repository-wide suite.

The fallback quality runner auto-detects repository-wide test commands. For
`artifact`, `targeted`, or `impacted`, override that default with the planned
final-tree verification command:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop \
  run-quality --command "test=<selected final-tree verification command>"
```

Keep configured mandatory gate categories and repository-required checks. An
override narrows the command to the reviewed impact surface; it must not turn a
real check into a no-op. Record any omitted full-suite command and the reason it
was unnecessary in `test-plan.md` and the final report.
