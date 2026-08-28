# Architecture

## What this service is

An immutable, double-entry ledger. It records money movements as balanced
journal entries and derives balances from that journal. It is the system of
record: if the ledger and any other system disagree, the ledger is right.

## The four invariants

Everything else is implementation detail. These are the promises:

1. **Every transaction balances.** `sum(debits) == sum(credits)`, exactly,
   in decimal arithmetic.
2. **Nothing is ever mutated.** No updates, no deletes. Corrections are new
   entries that reverse old ones.
3. **Balances are derived.** There is no stored balance column, ever. The
   journal is the only truth.
4. **Postings are idempotent.** The same idempotency key with the same body
   produces one transaction, no matter how many times it arrives.

If a change would violate one of these, the change is wrong.

## Layering

```
  HTTP  ──►  app/api/          routes, schemas, error mapping
                │              knows HTTP, knows nothing about ledger rules
                ▼
             app/domain/       ledger logic, invariants, exceptions
                │              knows ledger rules, knows nothing about HTTP
                ▼
             app/models/       SQLAlchemy tables and constraints
                │
                ▼
             PostgreSQL        the constraints that cannot be bypassed
```

The rule: dependencies point downward only. `app/domain` must never import
from `app/api`. This is what lets you test the ledger without a web server,
and later reuse it from a worker or CLI.

## Why append-only

The naive design stores a `balance` column and updates it on each posting.
That has two fatal problems.

**Correctness.** An update loses history. When a balance is wrong you have
no way to reconstruct how it got there, which in a financial system is
unacceptable — regulators, auditors and your own debugging all require the
trail.

**Scalability.** An updated row is a locked row. Every transaction touching
the platform cash account serialises behind every other one, so throughput
is capped at one account's write rate regardless of how many app servers you
run. Appends do not contend with each other.

Deriving balances is therefore both the safer and the faster choice. The
cost is that reads get more expensive as history grows, which is a solved
problem (snapshots) rather than a fundamental one.

## Concurrency model

Reads use READ COMMITTED — a slightly stale balance is acceptable.

Writes that read state and then write based on it use SERIALIZABLE with
automatic retry on SQLSTATE 40001. See `docs/adr/0002-isolation-levels.md`
for why, and `app/db.py::serializable_transaction` for how.

Uniqueness is enforced by database constraints, never by application checks.
An application check is a read followed by a write and therefore loses races;
a UNIQUE constraint does not. This applies to idempotency keys and to the
"reverse only once" rule.

## Scaling path

The system is designed so none of these are retrofits:

| Stage | Change | Why it works |
|---|---|---|
| 1 | Single node, append-only | No hot-row contention to begin with |
| 2 | Read replicas for balance queries | Reads are derived and tolerate staleness |
| 3 | Monthly range partitions on the journal | Indexes stay small, old data archivable |
| 4 | Balance snapshots + incremental sum | Reads become O(recent) instead of O(history) |
| 5 | Sharded counters for hot accounts | Turns one contended row into N uncontended ones |
| 6 | Outbox table for event emission | No commit/publish split-brain |

Partitioning is the one that must be decided early: a partitioned table's
primary key has to include the partition key. Retrofitting that onto a large
live table is genuinely painful, which is why `transactions` and
`transaction_lines` already carry `(id, created_at)` primary keys — see
ADR 0003.

Foreign keys referencing a partitioned table **are** supported, from
Postgres 12 onward, provided they reference the full unique key — so a
composite `(transaction_id, transaction_created_at)`, not a bare
`transaction_id`. This project drops those FKs anyway, as a deliberate
simplicity trade rather than a platform limit. ADR 0003 records the
alternatives; an earlier draft of both documents claimed the FKs were
impossible, which was true of Postgres 11 and has not been since 2019.

## Failure handling

| Condition | Response | Rationale |
|---|---|---|
| Unbalanced posting | 422 | Client error, correctable |
| Idempotency key reused with different body | 422 | Real client bug, must not be masked |
| Already reversed | 409 | State conflict |
| Serialization failure after retries | 503 + `Retry-After` | Transient; the client should retry |
| Anything unexpected | 500 with correlation ID, full trace logged | Never leak internals |

## Observability

Structured JSON logs on stdout with a request ID propagated through
`X-Request-ID`. Prometheus metrics at `/metrics`, labelled by route template
rather than raw path to keep cardinality bounded.

The metric that matters most is not latency — it is the trial balance. A
reconciliation job asserting `sum(debits) - sum(credits) == 0` across the
whole book is the cheapest, highest-value check in the system. Alert on it.

## Deliberate non-goals

- **Multi-currency in one transaction.** Rejected. Cross-currency movement
  is two transactions plus an explicit FX position.
- **Deleting or editing entries.** Never. Reversal only.
- **Floating-point money.** NUMERIC in the database, Decimal in Python.
- **Migrations on application startup.** A separate, explicit deploy step;
  replicas racing to migrate corrupts schemas.
