# ADR 0003 — Balance snapshots and monthly partitioning

**Status:** Accepted 2026-08-26. Amended the same day — two Postgres claims in the original draft were wrong. See "Amendment" below before relying on anything here.

## Amendment — 2026-08-26

This ADR was written against Postgres 11 semantics. The project runs
`postgres:17-alpine` (pinned in `docker-compose.yml` and `.github/workflows/ci.yml`).
Two load-bearing claims were verified against the running database and
found false. Both are corrected in place below; this note records what
changed so the reasoning is not silently rewritten.

**1. "Postgres does not support foreign keys targeting a partitioned table" — FALSE on 12+.**

Supported since Postgres 12. Verified:

```sql
CREATE TABLE p_tx (id varchar(36) NOT NULL, created_at timestamptz NOT NULL,
                   PRIMARY KEY (id, created_at)) PARTITION BY RANGE (created_at);
CREATE TABLE p_tx_2026_08 PARTITION OF p_tx
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE child (tx_id varchar(36) NOT NULL, tx_created_at timestamptz NOT NULL,
  FOREIGN KEY (tx_id, tx_created_at) REFERENCES p_tx(id, created_at));
-- CREATE TABLE

INSERT INTO child VALUES ('nope', '2026-08-15');
-- ERROR: insert or update on table "child" violates foreign key constraint "fk_child"
```

Created *and* enforced. What still fails is the **bare-id** form, for the
ordinary reason that `id` alone is not a unique key once the PK is
composite:

```sql
CREATE TABLE child2 (tx_id varchar(36) REFERENCES p_tx(id));
-- ERROR: there is no unique constraint matching given keys for referenced table "p_tx"
```

So dropping the FKs was never forced by partitioning. It is a choice, and
it is now recorded as one — see "Decision: foreign keys" below.

**2. "Postgres partitioning keys must be numeric; extract epoch as integer" — FALSE, and the proposed workaround does not work.**

`timestamptz` partitions directly. The `EXTRACT(EPOCH FROM created_at)`
expression this ADR originally proposed is rejected outright:

```sql
CREATE TABLE t_epoch (...) PARTITION BY RANGE (EXTRACT(EPOCH FROM created_at));
-- ERROR: functions in partition key expression must be marked IMMUTABLE
```

(`EXTRACT(EPOCH FROM timestamptz)` is STABLE, not IMMUTABLE — its result
depends on the session `TimeZone` setting.) The workaround was both
unnecessary and non-functional. The original SQL sketch was also not valid
Postgres declarative-partitioning syntax. Corrected below.

**What survived verification:** the primary-key requirement, which is the
decision this ADR exists to make.

```sql
CREATE TABLE t_badpk (..., PRIMARY KEY (id)) PARTITION BY RANGE (created_at);
-- ERROR: unique constraint on partitioned table must include all partitioning columns
-- DETAIL: PRIMARY KEY constraint on table "t_badpk" lacks column "created_at"
--         which is part of the partition key.
```

The `(id, created_at)` PK stands, and so does the reasoning for deciding it
before the tables carry data.

**Context**

The ledger design derives balances from a complete scan of transaction lines (`balance()` is O(account_history)). This is correct and sufficient today, but as the journal grows, reads slow down. There are two ways to address this:

1. **Store a balance column** — update it on each posting. Fast reads, but violates ADR 0001 (immutability, auditability), loses history, and creates row-level write contention on popular accounts.
2. **Balance snapshots** — periodically snapshot the accumulated balance at a point in time; subsequent balance queries sum only the (small) recent history since the snapshot. Fast reads, preserves history, no write contention.

Snapshots require partitioning the journal so old data can be archived or moved to cheaper storage. A ledger that lives forever on primary storage is a multi-million-dollar problem at scale.

**Decision**

Partition `transactions` and `transaction_lines` by `created_at` with monthly ranges. Do this from day one:

- **Primary key shape for Transaction:** `(id, created_at)`, not just `id`. Postgres requires the partition key in the PK.
- **Primary key shape for TransactionLine:** `(id, created_at)`, not just `id`.

### Decision: foreign keys

*(Rewritten 2026-08-26. The original text said FKs to a partitioned table
were impossible. They are not — see the Amendment. The conclusion is
unchanged; the reasoning is different, and that matters, because the old
reasoning would lead you to the wrong answer next time.)*

**No FK references *to* `transactions` or `transaction_lines`.**
`TransactionLine.transaction_id`, `IdempotencyKey.transaction_id`, and
`Transaction.reverses_id` are conceptual links validated in code, not
database constraints.

This is now a **deliberate simplicity trade, not a platform limitation.**
The alternative was live and was rejected on cost, not feasibility:

> **Rejected: composite FKs.** Carry a `transaction_created_at` copy on
> each referencing table and reference `(id, created_at)`. This is legal
> and enforced on Postgres 17, including after partitioning, and it is the
> only option that keeps referential integrity on `transaction_lines`
> permanently. Rejected because it adds a denormalised column to three
> tables, a `MATCH FULL` subtlety on the nullable self-reference (a
> composite FK defaults to `MATCH SIMPLE`, which skips the check entirely
> when any referencing column is NULL — so `reverses_id` set with
> `reverses_created_at` NULL would bypass the constraint silently), and a
> flush-ordering requirement in every posting path. Reconsider this if
> orphaned lines ever show up in reconciliation.

> **Rejected: standalone `UNIQUE (id)` alongside the composite PK.** Would
> keep bare-id FKs legal, but a unique constraint on a partitioned table
> must contain the partition key, so it forecloses partitioning entirely:
> `ERROR: unique constraint on partitioned table must include all
> partitioning columns`. This one genuinely is impossible, not merely
> costly.

What we accept by dropping the FKs:

- Orphaned `IdempotencyKey` rows are harmless (a race where the posting
  failed after the key was inserted).
- Orphaned `TransactionLine` rows are **not** harmless — a line pointing at
  a nonexistent transaction is a hole in the journal. Nothing but
  `post_transaction()` now prevents it. This is the real cost of the trade
  and it should be covered by the reconciliation job (milestone 5).
- `reverses_id` keeps its UNIQUE constraint, so "a transaction can only be
  reversed once" remains a database guarantee (ADR 0002). Only "the target
  exists" moves to code.

**Design: snapshots (future, not implemented yet, but shape decisions now)**

A `BalanceSnapshot` table (not implemented in this project):

```
id              UUID
account_id      FK -> accounts.id   (accounts is not partitioned; this FK is fine)
boundary        TIMESTAMPTZ (first instant of a month, UTC)
balance         NUMERIC(20, 4)      (sum of all lines with created_at < boundary)
```

**The boundary is exclusive, and the field is `timestamptz`, not `DATE`.**
Both of those are deliberate, and the original draft of this ADR got both
wrong — it used a `DATE` called `snapshot_date` and then reached for
`snapshot_date + timedelta(days=1)` to find the resume point. That is an
off-by-one waiting to happen in a money path:

- A `DATE` compared against a `timestamptz` is cast using the session
  `TimeZone`. Correct today only because `app/db.py` pins UTC on every
  connection, and silently wrong the moment that is not true.
- `+ 1 day` implies the snapshot covers all of `snapshot_date`, which
  contradicts "first day of month". Whichever way you read it, a line
  posted at exactly `2026-08-01T00:00:00Z` is either counted twice or
  dropped.

Half-open intervals `[boundary, as_of]` throughout, matching the partition
bounds above, so the two never disagree about which month a row belongs to.

To compute a balance:
```python
# Most recent snapshot whose boundary is at or before as_of.
snapshot = (
    select(BalanceSnapshot)
    .where(
        BalanceSnapshot.account_id == account_id,
        BalanceSnapshot.boundary <= as_of,
    )
    .order_by(BalanceSnapshot.boundary.desc())
    .limit(1)
)

if snapshot:
    # snapshot.balance covers created_at < boundary, so resume exactly at
    # boundary — no adjustment, which is the point of an exclusive bound.
    recent = sum_lines(account_id, since=snapshot.boundary, until=as_of)
    return snapshot.balance + recent
else:
    return sum_lines(account_id, since=None, until=as_of)  # full scan
```

This reduces the scan from months of data to ~1 month + one row lookup. Snapshots are computed offline (batch job once a month) and never updated.

**A snapshot is a cache, not a record.** It is derived data, so it does not
violate ADR 0001 — but that only holds if it is always reproducible from
the journal. Any snapshot job must be re-runnable and must produce an
identical result, and reconciliation (milestone 5) should verify a sample
of snapshots against a full recomputation. A snapshot that has silently
drifted from the journal is worse than no snapshot at all.

**Partitioning design**

Partition `transactions` and `transaction_lines` on `created_at` with monthly RANGE partitions. `timestamptz` is a valid partition key directly — no epoch conversion, and the conversion this ADR originally proposed is rejected by Postgres anyway (see Amendment):

```sql
-- Created by Alembic migration once the schema is stable.
CREATE TABLE transactions (
    id          varchar(36)  NOT NULL,
    created_at  timestamptz  NOT NULL,
    memo        varchar,
    currency    varchar(3)   NOT NULL,
    reverses_id varchar(36),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- One child table per month. Upper bound is exclusive, so consecutive
-- months abut exactly with no gap and no overlap.
CREATE TABLE transactions_2026_08 PARTITION OF transactions
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE transactions_2026_09 PARTITION OF transactions
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
```

Two operational notes that are easy to miss:

- **Bounds are compared in UTC**, because `app/db.py` sets `timezone = 'UTC'`
  on every physical connection. A bare `'2026-08-01'` literal is therefore
  unambiguous here — but it would not be on a connection with a different
  `TimeZone`, and a row can land in the wrong month if that ever drifts.
- **A row with no matching partition is rejected**, not silently stored:
  `ERROR: no partition of relation "transactions" found for row`. Partition
  creation is therefore a scheduled operational task with a deadline, not a
  cleanup chore. Create ahead of time (see Remaining questions) or add a
  `DEFAULT` partition as a safety net and alert on anything landing in it.

**What this means**

| Constraint | Before | After | Why |
|---|---|---|---|
| PK shape | `id` | `(id, created_at)` | Partition key must be in PK |
| Querying by id | `.filter(id=x)` | Still works, but scans **every** partition | No partition key in the filter means no pruning |
| Uniqueness of `id` alone | Guaranteed by `PRIMARY KEY (id)` | **Not guaranteed** | `(id, created_at)` permits two rows sharing an id |
| FK targeting these tables | `fk_idempotencykey_transaction_id` | Removed by choice, not necessity | Composite FKs would work (see Amendment); we took the simpler trade |
| Archival | Import new data; old data is live forever | Drop/archive old partitions quarterly | Cheap storage cleanup |
| Point-in-time queries | Full scan; O(history) | Snapshot + recent; O(1 month) | Justification for the complexity |

**Rejection alternatives**

- **No partitioning, just snapshots** — snapshots help reads but don't help storage or archival. Viable if the ledger stays small (<100GB).
- **Hash or list partitioning** — could partition by `account_id` instead. Doesn't help archival (can't drop old data), and distributes recent data across partitions (more complex).
- **Separate archive table** — manually move old transactions to a history table. Works but is a data-movement operation that must be atomic, error-prone, and complex to maintain.

**Consequences**

**Accepted:**
- PK queries by `id` alone need a partition key in the filter. SQLAlchemy/ORM code doesn't automatically know this, so write queries carefully: `session.query(Transaction).filter_by(id=x)` actually works (Postgres scans all partitions) but is slower than ideal. Better to include `created_at` in the filter if you have it.
- **`id` alone is no longer unique.** `PRIMARY KEY (id, created_at)` permits two rows sharing an `id` with different timestamps. Application-generated UUIDv4 makes a collision vanishingly unlikely, but it stops being the *database's* promise, and every lookup by bare `id` becomes a query that can in principle return more than one row. This cannot be patched with `UNIQUE (id)` — that is the one thing partitioning genuinely forbids.
- `reverses_id` as a self-FK on `transactions` is no longer a database constraint. We rely on the UNIQUE constraint on `reverses_id` plus code validation to enforce "a transaction can only be reversed once." This is acceptable because:
  - The UNIQUE constraint still fires on insert and catches the race.
  - We don't need a FK constraint to validate the target exists — the calling code already knows the original transaction.
- Schema changes become migrations (not just model changes) because partitions must be created explicitly.

**Not accepted (out of scope):**
- Sharded counters for hot accounts (milestone 8, scaling stage 5) — that's a separate decision.
- Event outbox (ADR milestone, scaling stage 6) — separate.

---

**Rationale for deciding this now**

If `created_at` is not in the Transaction PK from day one, retrofitting it later requires:
1. Create a new partitioned table with the right PK.
2. Copy all data over (hours to days for large datasets).
3. Repoint FKs (can't, so code changes).
4. Drop the old table.

This is a deploy-day nightmare for a "big data" system. Fintech systems accumulate data constantly and rarely have a maintenance window to do this safely. Deciding the PK shape now — even though snapshots aren't built — is the only sane path.

---

## Remaining questions

1. Should the first partition extend backward in time (e.g., to 2020) or forward (e.g., to current month + 6 months buffer)? Recommend: current month + 1 month buffer (partition creation is a routine operation).
2. Should old partitions be automatically dropped, or manually archived to cold storage? Recommend: manual (safer, auditable), with a runbook.
3. Should we add indexes within partitions, or rely on the partition key for pruning? Recommend: local indexes on `(account_id, created_at)` per partition (Postgres 11+ supports this).
