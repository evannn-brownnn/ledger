"""ORM models.

>>> THIS IS YOURS TO WRITE. <<<

Alembic's autogenerate walks `Base.metadata`, so every model class must be
imported here or migrations will silently miss it.

--------------------------------------------------------------------------
SPEC — what you need to define
--------------------------------------------------------------------------

`Account`
    id            UUID pk
    name          unique, not null
    normal_balance  'debit' | 'credit'   (CHECK constraint)
    currency      3-char, must be in settings.supported_currencies
    created_at

    Why `normal_balance`: asset and expense accounts increase on the debit
    side; liability, equity and revenue accounts increase on the credit
    side. Storing it lets `balance()` return a signed number the caller can
    use directly instead of pushing sign logic onto every consumer.

`Transaction`
    id            UUID pk
    memo          text
    currency      3-char
    reverses_id   nullable FK -> transactions.id, UNIQUE
    created_at    indexed

    The UNIQUE on reverses_id is how you make "a transaction can only be
    reversed once" a database guarantee rather than an application check.
    Enforce invariants in the schema wherever you can; application checks
    lose races, constraints do not.

    There is no status column and no update path. A transaction is a fact
    that happened.

`TransactionLine`
    id              UUID pk
    transaction_id  FK -> transactions.id, indexed
    account_id      FK -> accounts.id, indexed
    direction       'debit' | 'credit'  (CHECK)
    amount          NUMERIC(20, 4), CHECK (amount > 0)

    Amount is always positive and `direction` carries the sign. This means
    the balanced-transaction invariant is a plain sum comparison, and a
    negative amount is unrepresentable rather than merely discouraged.

    NEVER use FLOAT or DOUBLE for money. Use NUMERIC, and Decimal in Python.

    Index hint: you will constantly query lines by (account_id, created_at)
    to compute balances. A composite index there matters more than the
    single-column ones once the table is large.

`IdempotencyKey`
    key             varchar pk
    request_hash    sha256 of the normalised request body
    transaction_id  FK -> transactions.id
    created_at

    `request_hash` exists so that reusing a key with a *different* body is
    detectable — that is a client bug and must return 422, not silently
    replay the original response.

`AuditEvent`
    id            UUID pk
    actor         who did it
    action        what they did
    entity_type   / entity_id  what it happened to
    payload       JSONB snapshot
    created_at

--------------------------------------------------------------------------
PARTITIONING (milestone 5, but design for it now)
--------------------------------------------------------------------------
`transactions` and `transaction_lines` should eventually be RANGE-partitioned
on created_at, monthly. Two consequences you must accept up front:

  - A partitioned table's primary key must include the partition key. So the
    PK becomes (id, created_at), not just id.
  - Foreign keys *referencing* a partitioned table are not supported. Plan
    for that before you write the FKs, not after.

Retrofitting partitioning onto a large live table is genuinely painful.
Decide now.
"""

from __future__ import annotations

from app.models.base import Base, CreatedAt, UUIDPrimaryKey, new_uuid, utcnow

# TODO(you): from app.models.ledger import Account, Transaction, ...

__all__ = [
    "Base",
    "CreatedAt",
    "UUIDPrimaryKey",
    "new_uuid",
    "utcnow",
]
