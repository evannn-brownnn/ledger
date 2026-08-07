# ADR 0003 — Balance snapshots and monthly partitioning

**Status:** Proposed (decides primary-key shape; must be decided before Transaction/TransactionLine models are written)

**Context**

The ledger design derives balances from a complete scan of transaction lines (`balance()` is O(account_history)). This is correct and sufficient today, but as the journal grows, reads slow down. There are two ways to address this:

1. **Store a balance column** — update it on each posting. Fast reads, but violates ADR 0001 (immutability, auditability), loses history, and creates row-level write contention on popular accounts.
2. **Balance snapshots** — periodically snapshot the accumulated balance at a point in time; subsequent balance queries sum only the (small) recent history since the snapshot. Fast reads, preserves history, no write contention.

Snapshots require partitioning the journal so old data can be archived or moved to cheaper storage. A ledger that lives forever on primary storage is a multi-million-dollar problem at scale.

**Decision**

Partition `transactions` and `transaction_lines` by `created_at` with monthly ranges. Do this from day one:

- **Primary key shape for Transaction:** `(id, created_at)`, not just `id`. Postgres requires the partition key in the PK.
- **Primary key shape for TransactionLine:** `(id, created_at)`, not just `id`.
- **No FK references *to* these tables.** Postgres does not support foreign keys targeting a partitioned table. `IdempotencyKey.transaction_id` and any reverse reference must be conceptual links (validated in code), not database constraints. This is acceptable because:
  - Orphaned `IdempotencyKey` rows are harmless (a race where the posting failed after the key was inserted).
  - `reverses_id` (self-FK on Transaction) cannot be partitioned together with its target anyway — must be handled via code/trigger or accepted as a design gap for now.

**Design: snapshots (future, not implemented yet, but shape decisions now)**

A `BalanceSnapshot` table (not implemented in this project):

```
id              UUID
account_id      FK -> accounts.id
snapshot_date   DATE (first day of month)
balance         NUMERIC(20, 4)
```

To compute a balance:
```python
# Find the most recent snapshot at or before as_of
snapshot = session.query(BalanceSnapshot)
    .filter(account_id, snapshot_date <= as_of)
    .order_by(snapshot_date.desc())
    .first()

# Sum only lines since the snapshot
if snapshot:
    since = snapshot.snapshot_date + timedelta(days=1)
    recent = sum_since(account_id, since, as_of)
    return snapshot.balance + recent
else:
    return sum_all(account_id, as_of)  # Before first snapshot, fall back to full scan
```

This reduces the scan from months of data to ~1 month + one row lookup. Snapshots are computed offline (batch job once a month) and never updated.

**Partitioning design**

Partition `transactions` and `transaction_lines` on `created_at` with monthly RANGE partitions:

```sql
-- Created by Alembic migration once the schema is stable
PARTITION BY RANGE (EXTRACT(EPOCH FROM created_at)) (
    PARTITION jan_2025 VALUES FROM (1704067200) TO (1706745600),
    PARTITION feb_2025 VALUES FROM (1706745600) TO (1709251200),
    ...
    PARTITION jan_2026 VALUES FROM (1735689600) TO (1738368000)
)
```

(Postgres partitioning keys must be numeric; `created_at` is datetime, so extract epoch as integer).

**What this means**

| Constraint | Before | After | Why |
|---|---|---|---|
| PK shape | `id` | `(id, created_at)` | Partition key must be in PK |
| Querying by id | `.filter(id=x)` | Still works; Postgres scans the single partition | Transparent at query time |
| FK targeting these tables | `fk_idempotencykey_transaction_id` | Not supported; remove constraint | Partitioned tables can't be FK targets |
| Archival | Import new data; old data is live forever | Drop/archive old partitions quarterly | Cheap storage cleanup |
| Point-in-time queries | Full scan; O(history) | Snapshot + recent; O(1 month) | Justification for the complexity |

**Rejection alternatives**

- **No partitioning, just snapshots** — snapshots help reads but don't help storage or archival. Viable if the ledger stays small (<100GB).
- **Hash or list partitioning** — could partition by `account_id` instead. Doesn't help archival (can't drop old data), and distributes recent data across partitions (more complex).
- **Separate archive table** — manually move old transactions to a history table. Works but is a data-movement operation that must be atomic, error-prone, and complex to maintain.

**Consequences**

**Accepted:**
- PK queries by `id` alone need a partition key in the filter. SQLAlchemy/ORM code doesn't automatically know this, so write queries carefully: `session.query(Transaction).filter_by(id=x)` actually works (Postgres scans all partitions) but is slower than ideal. Better to include `created_at` in the filter if you have it.
- `reverses_id` as a self-FK on `transactions` is no longer a database constraint. We rely on the UNIQUE constraint on `reverses_id` plus code validation to enforce "a transaction can only be reversed once." This is acceptable because:
  - The UNIQUE constraint still fires on insert and catches the race.
  - We don't need a FK constraint to validate the target exists — the calling code already knows the original transaction.
- Schema changes become migrations (not just model changes) because partitions must be created explicitly.

**Not accepted (out of scope):**
- Sharded counters for hot accounts (ADR milestone 5, scaling stage 5) — that's a separate decision.
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
