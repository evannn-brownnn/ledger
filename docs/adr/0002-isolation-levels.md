# ADR 0002 — SERIALIZABLE for writes, with retry

Status: accepted

## Context

Postgres defaults to READ COMMITTED. That is not sufficient for any
operation that reads state and then writes based on it.

Concrete failure. Two withdrawals of 100 arrive simultaneously against a
balance of 100:

```
T1: SELECT balance -> 100        T2: SELECT balance -> 100
T1: 100 >= 100, ok               T2: 100 >= 100, ok
T1: INSERT withdrawal 100        T2: INSERT withdrawal 100
T1: COMMIT                       T2: COMMIT
                     balance is now -100
```

Nothing here is a bug in the code. It is READ COMMITTED behaving exactly as
specified. The write skew is invisible to any amount of careful application
logic.

## Decision

Writes whose correctness depends on state they read run at SERIALIZABLE,
via `app.db.serializable_transaction`, which retries on SQLSTATE 40001
(serialization failure) and 40P01 (deadlock) with exponential backoff and
jitter.

Reads run at READ COMMITTED. A marginally stale balance read is acceptable
and the throughput difference is real.

Uniqueness constraints — idempotency keys, reverse-once — are enforced by
UNIQUE indexes rather than by isolation level. A constraint is cheaper and
cannot lose a race.

## Consequences

**Good**

- Write skew is impossible by construction rather than by vigilance.
- The retry loop lives in one place, not scattered through domain code.
- Domain logic reads like straightforward single-threaded code.

**Bad**

- Transactions can abort under contention and must be retried. Callers must
  tolerate a handler running more than once, so no side effects outside the
  session inside a retried block.
- Throughput is lower than READ COMMITTED under heavy contention.
- Retries can be exhausted; the API returns 503 with `Retry-After`.

## Alternatives rejected

**`SELECT ... FOR UPDATE`.** Works, and is often the right answer for a
single well-known row. Rejected as the default because it requires the
developer to remember to take the lock, and to take it on the right rows in
the right order — forget either and you get silent corruption or a deadlock.
SERIALIZABLE fails loudly instead. Still appropriate for targeted hot paths
once measured.

**Advisory locks.** Effective but invisible to the query planner and easy to
leak across a connection pool.

**Optimistic version columns.** Reintroduces a mutable row to contend on,
which contradicts ADR 0001.

## Jitter, specifically

Backoff without jitter makes conflicting transactions retry in lockstep and
collide again. `wait_exponential_jitter` is not decoration.
