# ADR 0001 — The journal is immutable and balances are derived

Status: accepted

## Context

The service must report account balances. The obvious implementation stores
a `balance` column on `accounts` and updates it inside each posting.

## Decision

No stored balance. Postings append immutable rows to `transactions` and
`transaction_lines`. Balances are computed from those rows. Corrections are
new reversing entries, never edits or deletes.

## Consequences

**Good**

- Full auditability. Every balance can be explained by the entries that
  produced it, and any historical balance can be reconstructed with `as_of`.
- No write contention on hot accounts. Appends do not lock each other, so
  throughput is not capped by the busiest account.
- Corrections are visible. A reversal is a fact in the journal, which is
  what an auditor needs to see.
- Bugs are recoverable. If posting logic was wrong for a day, the raw
  entries are still there to reprocess.

**Bad**

- Reads get more expensive as history grows. Mitigated by balance snapshots
  (ADR 0003, milestone 7), not by abandoning the design.
- Storage grows forever. This is correct for a financial record and is
  managed with partitioning and archival, not deletion.
- More moving parts than a single mutable column.

## Alternatives rejected

**Mutable balance column.** Fast to read and simple, but destroys history
and makes every writer to a popular account serialise behind a row lock.
Both problems are fatal in this domain.

**Event sourcing with a separate read model.** Similar benefits, materially
more machinery — a projection to build, keep consistent, and rebuild. The
journal *is* the event log here, so the extra layer buys little.

## Enforcement

There is no `updated_at` column and no UPDATE path in the domain layer. If
you find yourself wanting one, the answer is a reversing entry.
