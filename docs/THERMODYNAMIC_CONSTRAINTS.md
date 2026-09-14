# Scaling and idempotency notes

This file documents the two additions in ADR 0004 and ADR 0005 — the
volume-scaled partition policy and the single-process idempotency fast
path — and the chaos harness used to exercise the second one. It exists so
a reader doesn't need to open the code to see the shape of either, and so
this project's own scale claims are stated once, explicitly, rather than
left to be inferred from the file name this document happens to live at.

## Partition granularity thresholds

`app.partitioning.metadata.RADIX_THRESHOLDS`, decided in
[ADR 0004](adr/0004-dynamic-partition-granularity.md):

| Row-count threshold | Interval |
|---|---|
| below 10⁶ | none — single unpartitioned table |
| 10⁶ | monthly |
| 10⁸ | weekly |
| 10⁹ | daily |
| 10¹⁰ | hourly |
| 10¹² | ceiling — `interval_for_row_count` raises past this point |

These thresholds are a documented policy for this exercise, not numbers
measured against a real workload — see ADR 0004's Consequences section for
that caveat in full. The ceiling exists to say plainly where time-range
partitioning on one Postgres instance stops working, not to imply the
scheme scales past it.

## Idempotency index contract

`app.idempotency.protocol.IdempotencyIndex`, decided in
[ADR 0005](adr/0005-in-process-idempotency-index.md), is a `Protocol` with
one method:

```python
def check_and_insert(self, key: str, request_hash: str) -> IdempotencyOutcome:
    ...  # "inserted" | "duplicate_same" | "duplicate_conflict"
```

`app.idempotency.local_index.ShardedLocalIdempotencyIndex` is one
single-process implementation of it. Restated from the ADR because it is
the single most important fact about this contract: **this index is a
pre-filter, never an authority.** The UNIQUE constraint on
`IdempotencyKey.key` (`app/models/ledger.py`) remains the only mechanism
that decides whether a transaction is created. This index cannot see
across processes, so it cannot be correct on its own the moment there is
more than one.

## Chaos simulation profile

`tests.chaos_profiles.SimulationChaosProfile` describes a fault scenario:
a drop rate, a jitter range, and a call count, indexed by an order-of-
magnitude `scale_exponent` from 2 to 6. `tests.chaos_injector` wraps a real
`IdempotencyIndex` to inject those faults and fires a bounded, concurrent
thundering herd at one key.

What the checked-in suite (`tests/test_idempotency_chaos.py`) actually
proves: for every scale it runs, exactly one caller among many concurrent,
occasionally-dropped attempts is told "inserted," and every other attempt —
including every dropped-and-retried one — resolves to "duplicate_same."

What it does **not** prove, at any exponent: cross-process correctness. A
single OS process cannot demonstrate the failure mode ADR 0005 describes,
no matter how high the concurrent call count climbs. For exponents 5 and 6
the executed call count is also capped well below a literal 10⁵/10⁶ so the
suite finishes in seconds — the `scale_exponent` field names which scenario
a profile represents, not a claim that that many calls were literally run.
The partitioning ceiling at 10¹² is likewise never executed against a real
table anywhere in this repo; it is a documented number in ADR 0004, checked
only as arithmetic in `tests/test_partitioning.py`.

## Practical applications — analogy only

None of the following is a claim about this repository, which runs on
Docker Compose against one Postgres instance. It's here because the
patterns above have real, larger-scale counterparts worth naming
correctly:

- **Graduated partition widths** resemble how Vitess and Citus reshard as
  a table grows, and how DynamoDB adjusts partition allocation under
  adaptive capacity — a policy that responds to volume rather than a
  size fixed at design time.
- **A local fast-path in front of a strongly-consistent store** is close
  to how idempotency keys work in production payment systems — Stripe's
  publicly documented idempotency-key design is the standard reference,
  and it is worth citing specifically *because* it is database-backed,
  not in-process. That's the accurate real-world version of this
  project's own invariant 4, and it underscores ADR 0005's scope limit
  rather than arguing against it: a fast path is a latency optimization
  in front of a durable store, never a replacement for one.
- **Fault injection under load** is the same idea behind Chaos Monkey and
  Jepsen-style testing of distributed systems: inject drops and races
  deliberately, in a controlled setting, rather than discover them in
  production.

Read the table and the contract above as documentation of a mechanism this
project built and tested at a small scale. Read this section as naming
what that mechanism resembles elsewhere — nothing more.
