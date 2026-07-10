# Evidence Contracts

## Contents

- [Documents and versions](#documents-and-versions)
- [Compatibility behavior](#compatibility-behavior)
- [Inspect and migrate](#inspect-and-migrate)
- [Machine-readable output](#machine-readable-output)
- [Persistence guarantees](#persistence-guarantees)

## Documents And Versions

Evidence schema versioning is separate from the user configuration schema.
Versions 0.6.0 and later write evidence schema `1` to:

| Document | Kind | Default path |
| --- | --- | --- |
| Full-loop state | `loop-state` | `.codex/dev-loop/loop-state.json` |
| Standalone TDD ledger | `tdd` | `.codex/evidence/tdd/ledger.json` |
| Standalone review ledger | `review` | `.codex/evidence/review/ledger.json` |

Every current document has top-level `schema_version`, `kind`, and
`core_version` fields. Existing evidence payload fields and unknown
host-owned extension fields are preserved during migration.

## Compatibility Behavior

- An unversioned 0.5.x document is schema `0`. The core upgrades it in memory;
  the next successful mutating command writes schema `1`.
- A schema `1` document must have the correct `kind`, a non-empty
  `core_version`, and correctly typed required containers.
- Invalid JSON, invalid container types, kind mismatches, and schema versions
  newer than the installed core are rejected.
- A corrupt or future canonical loop state blocks standalone writes. The
  single-source-of-truth guard fails closed because it cannot prove that no
  loop is active.

## Inspect And Migrate

Run these commands from the target repository. Global options precede the
subcommand:

```bash
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop --workspace . doctor
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop --workspace . migrate-evidence --dry-run
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop --workspace . migrate-evidence
```

`doctor` is read-only. It exits `0` for current or absent evidence and `1` for
`needs-migration` or an error. `migrate-evidence --dry-run` previews every
document without writing. Migration validates all discovered documents before
the first write; schema/contract errors therefore cannot produce a partial
migration.

## Machine-Readable Output

Use `--json` on `doctor`, `migrate-evidence`, `version`, or `fingerprint`.
Automation should inspect the `status` field instead of parsing human text.
Doctor statuses are `ok`, `needs-migration`, and `error`; migration also uses
`migrated` and `up-to-date`.

```bash
python <skill-dir>/scripts/dev_loop_harness.py version --json
python <skill-dir>/scripts/dev_loop_harness.py --root .codex/dev-loop doctor --json
```

## Persistence Guarantees

- Evidence writes validate the complete document before touching the target.
- Each file is written to a unique temporary file in the same directory,
  flushed, then atomically replaced.
- A failed write removes its temporary file.
- Multi-document migration prevalidates the set and writes each file
  atomically; an operating-system I/O failure can still stop between files, so
  rerun `doctor` after an interrupted migration.
