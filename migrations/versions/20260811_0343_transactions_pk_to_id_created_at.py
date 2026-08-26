"""transactions pk to (id, created_at)

Revision ID: 0da3c0e77b31
Revises: 7ec5c01c2ff8
Created: 2026-08-11 03:43:22.589484+00:00

Hand-written. Alembic's autogenerate does not detect primary key changes,
so the original draft of this file came out with `pass` in both directions
and the model/schema disagreement went unnoticed until it was tested
against a live database.

REVIEW CHECKLIST — autogenerate is a draft, not an oracle:

  [x] Does downgrade() actually reverse upgrade()? Test it.
      -> Yes. CI exercises it via `alembic downgrade base && alembic
         upgrade head`. See the caveat in downgrade() about data that the
         relaxed constraints permit.
  [x] Any new index on a large table -> use postgresql_concurrently=True
      and set this migration non-transactional, or you lock writes.
      -> ADD PRIMARY KEY builds a unique index under ACCESS EXCLUSIVE.
         Fine on an empty table; see PRODUCTION NOTE in upgrade().
  [x] Adding a NOT NULL column to a populated table needs a server_default
      or a three-step deploy.
      -> n/a. No columns are added or altered.
  [x] Did autogenerate try to DROP something you meant to keep?
      -> n/a, autogenerate produced nothing. Note by hand that
         uq_transactions_reverses_id is deliberately NOT touched: it is the
         reverse-once guarantee (ADR 0002).
  [x] Read the generated SQL: `alembic upgrade head --sql`

--------------------------------------------------------------------------
WHY THE FK DROPS ARE NOT OPTIONAL HERE
--------------------------------------------------------------------------
Postgres binds a foreign key to the *specific unique index* backing the
referenced key. Three FKs reference transactions(id), served by the
pk_transactions index, so dropping that PK fails outright:

    ERROR: cannot drop constraint pk_transactions on table transactions
    because other objects depend on it
    DETAIL: constraint fk_transactions_reverses_id_transactions ...
            constraint fk_idempotency_keys_transaction_id_transactions ...
            constraint fk_transaction_lines_transaction_id_transactions ...

Adding a second UNIQUE(id) does not re-point them; the dependency is on the
index, not on the column. The FKs have to come off before the PK can move.

DROP ... CASCADE would also work and is shorter. Do not use it in a
migration: it silently drops whatever depends on the constraint, which is
not necessarily the three things you think it is, and it leaves no record
of what was removed.

--------------------------------------------------------------------------
WHY THEY DO NOT GO BACK ON
--------------------------------------------------------------------------
This is a decision, not a platform limit. Composite foreign keys targeting
a partitioned table DO work on Postgres 12+ and this project runs 17 —
carrying a transaction_created_at column on each referencing table would
have preserved full referential integrity, before and after partitioning.

It was rejected on cost, not feasibility: a denormalised column on three
tables, a MATCH FULL subtlety on the nullable self-reference, and a
flush-ordering requirement in every posting path. See ADR 0003, "Decision:
foreign keys", which records the alternatives and what each one costs.

The consequence to keep in view: an orphaned transaction_line is now
possible at the database level, and only post_transaction() prevents it.
That is a hole in the journal, unlike an orphaned idempotency key, which
ADR 0003 accepts as harmless. Reconciliation (milestone 5) should look for
orphans.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0da3c0e77b31"
down_revision: str | None = "7ec5c01c2ff8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Release the dependency on the pk_transactions index. Must happen
    #    before the primary key can be dropped.
    op.drop_constraint(
        op.f("fk_transaction_lines_transaction_id_transactions"),
        "transaction_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_idempotency_keys_transaction_id_transactions"),
        "idempotency_keys",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_transactions_reverses_id_transactions"),
        "transactions",
        type_="foreignkey",
    )

    # 2. Swap the primary key. created_at trails id deliberately: a B-tree
    #    only helps when the filter includes the leftmost column, and
    #    lookup by id is the most common access path in the system.
    #    uq_transactions_reverses_id is independent of pk_transactions and
    #    is left alone on purpose.
    op.drop_constraint(op.f("pk_transactions"), "transactions", type_="primary")
    op.create_primary_key(op.f("pk_transactions"), "transactions", ["id", "created_at"])

    # PRODUCTION NOTE — not needed here, needed on a populated table.
    #
    # create_primary_key builds a unique index while holding ACCESS
    # EXCLUSIVE, blocking reads and writes for the duration. On a large
    # transactions table, build the index first and adopt it:
    #
    #     CREATE UNIQUE INDEX CONCURRENTLY pk_transactions_idx
    #       ON transactions (id, created_at);
    #     ALTER TABLE transactions
    #       ADD CONSTRAINT pk_transactions PRIMARY KEY USING INDEX
    #       pk_transactions_idx;
    #
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block, and
    # migrations/env.py sets transaction_per_migration=False, so this would
    # need that changed first. The ADD CONSTRAINT still takes ACCESS
    # EXCLUSIVE, but only briefly, since the index already exists.


def downgrade() -> None:
    # This is a reverse, not an undo, and it can legitimately fail.
    #
    # The composite PK permits two rows sharing an id with different
    # created_at values, so PRIMARY KEY (id) may find duplicates. The
    # absent FKs permit orphaned lines and idempotency keys, so recreating
    # them may find violations. In both cases Postgres refuses rather than
    # discarding rows, which is the correct outcome — but it means a
    # rollback on a live database needs those checked first:
    #
    #     SELECT id FROM transactions GROUP BY id HAVING count(*) > 1;
    #     SELECT l.id FROM transaction_lines l
    #       LEFT JOIN transactions t ON t.id = l.transaction_id
    #      WHERE t.id IS NULL;
    #
    # On an empty database (CI's downgrade-base-then-upgrade-head check)
    # both are trivially satisfied.
    op.drop_constraint(op.f("pk_transactions"), "transactions", type_="primary")
    op.create_primary_key(op.f("pk_transactions"), "transactions", ["id"])

    # Recreated in reverse order of the drops above. The FKs can only be
    # added back once PRIMARY KEY (id) exists to target.
    op.create_foreign_key(
        op.f("fk_transactions_reverses_id_transactions"),
        "transactions",
        "transactions",
        ["reverses_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_idempotency_keys_transaction_id_transactions"),
        "idempotency_keys",
        "transactions",
        ["transaction_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_transaction_lines_transaction_id_transactions"),
        "transaction_lines",
        "transactions",
        ["transaction_id"],
        ["id"],
    )
