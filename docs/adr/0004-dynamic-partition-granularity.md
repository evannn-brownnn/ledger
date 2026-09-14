# ADR 0004 — Volume-scaled partition granularity

Status: accepted — extends ADR 0003; does not reopen its primary-key decision

## Context

ADR 0003 decided that `transactions` and `transaction_lines` are partitioned
by `created_at` with fixed monthly RANGE partitions, chosen up front because
Postgres requires the partition key in the primary key and retrofitting that
onto a live table means a full copy. That reasoning stands untouched here.

What ADR 0003 didn't settle is partition *width*. A fixed monthly interval
is a single point on a spectrum, chosen for a ledger of unspecified size.
Two failure modes sit on either side of it:

- A ledger with a few hundred or thousand rows gets a monthly partition
  scheme it does not need yet: extra entries in the system catalog, an
  autovacuum worker per partition, and a query planner pruning across
  children that could just as well be one table.
- A ledger growing toward the billions-of-rows range this exercise targets
  outgrows a monthly partition long before the next one starts: each
  partition holds too much data for the indexing and archival benefits
  ADR 0003 was written to get.

Fixed width doesn't track load. That's the defect this ADR fixes.

## Decision

Partition width is chosen by accumulated row count, via
`app.partitioning.metadata.interval_for_row_count`:

| Row-count threshold | Interval | Rationale |
|---|---|---|
| below 10⁶ | none — single unpartitioned table | Postgres holds low hundreds of thousands of rows in one table with no planner or autovacuum penalty; partitioning here buys nothing |
| 10⁶ | monthly | where partition overhead starts paying for itself |
| 10⁸ | weekly | |
| 10⁹ | daily | |
| 10¹⁰ | hourly | |
| 10¹² | ceiling — no finer interval is offered | past this, no partition width fixes it on one Postgres instance; the honest next step is horizontal sharding (Citus, Vitess, or similar), which is a new-infrastructure decision this ADR does not make |

Everything else in ADR 0003 is reaffirmed without change: PK shape
`(id, created_at)` on both `Transaction` and `TransactionLine`, RANGE
partitioning on `created_at`, no FK targeting either table — a deliberate
simplicity trade per ADR 0003's amendment, not a Postgres limitation, so
`IdempotencyKey.transaction_id` remains a conceptual link only, exactly as
ADR 0003 already required — and the `BalanceSnapshot` sketch is untouched.
The PK swap and FK removal are not merely decided: they are already applied,
via migrations `0da3c0e77b31` and `20260828_0349_harden_model_constraints`.
What remains undone, on both ADR 0003 and this ADR, is the physical
partitioning itself — no `PARTITION BY RANGE` table or child partition
exists yet for either journal table.

This is a graduated scheme, not a live-resizing one. Postgres cannot
retroactively repartition an existing partition to a different width.
Crossing a threshold changes the width of *new* partitions created after
that point; data already sitting in wider partitions stays there unless an
explicit, separately-planned backfill migration moves it. Nothing in this
ADR builds that migration — matching ADR 0003's own precedent of deciding
the shape without implementing the mechanism yet.

## Consequences

**Good**

- Partition width tracks actual load instead of being fixed at a guess.
- A small ledger — the case this project actually runs as, on Docker
  Compose against one Postgres instance — never pays for partitioning it
  doesn't need.
- Nothing about ADR 0003's PK shape, archival strategy, or FK removal
  changes, so no model rewrite follows from this decision.

**Bad**

- Mixed partition widths over a table's lifetime is materially more
  operational bookkeeping than ADR 0003's one-shot monthly scheme: whoever
  creates partitions ahead of time (a cron job, a migration, a runbook
  step) now has to check current volume against this table before choosing
  a width, rather than always creating "next month."
- The thresholds above are the round numbers this exercise specified, not
  numbers measured against a real workload. Said plainly rather than
  quietly corrected: in production, Postgres partitioning is rarely worth
  adopting below roughly 10⁶–10⁷ rows, and this project has no measured
  workload at all. Treat the table as a documented policy to test the
  *mechanism* against, not as tuning advice for an unrelated system.
- The 10¹² ceiling is a documentation boundary, not a claim this repo
  reaches that scale, or should. Its only job is to state honestly where
  "just partition harder" stops being the answer, rather than implying the
  scheme scales forever.
- No migration tooling is added to actually create graduated partitions.
  This ADR decides the policy `interval_for_row_count` encodes; wiring it
  into a real Alembic migration or ops runbook is future work, same as the
  snapshot table in ADR 0003. This is a narrower gap than it might sound:
  the PK/FK groundwork both ADRs require is already live in the schema —
  what is missing is specifically the `PARTITION BY RANGE` declaration and
  its child tables, not the prerequisites for one.

## Alternatives rejected

**Keep ADR 0003's fixed-monthly-forever.** Simpler, and correct at exactly
one scale. Rejected because it either over-partitions a small ledger or
under-partitions a large one, and the target range here spans both ends.

**Always-hourly from day one.** Avoids ever needing to change width, at the
cost of partition-count explosion (and an autovacuum worker per partition)
for a ledger that may never reach the volume that justifies it.

**Partition by row count instead of time range.** Rejected for the same
reason ADR 0003 chose `created_at`: archival ("drop transactions older than
N years") needs a time boundary, not a count boundary, and row-count
partitioning breaks that use case entirely.

**`pg_partman`-managed automatic repartitioning.** The genuinely better
production answer to the graduated-scheme bookkeeping problem above.
Rejected here only because adopting it is a new infrastructure dependency
decision, and CLAUDE.md is explicit that those aren't made without being
asked. Worth revisiting if this policy is ever operated for real.
