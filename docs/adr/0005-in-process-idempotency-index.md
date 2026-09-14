# ADR 0005 — Single-process idempotency fast path

Status: accepted — amends ADR 0002; does not supersede or weaken it

## Context

ADR 0002 decided that idempotency and "reverse once" uniqueness are
enforced by UNIQUE indexes rather than by isolation level, because a
constraint cannot lose a race the way a read-then-write check can.
`IdempotencyKey.key` (`app/models/ledger.py`) is that constraint: a varchar
primary key, so a concurrent duplicate insert fails at the database rather
than being missed by application logic. `post_transaction`'s own docstring
(`app/domain/ledger.py`) states the resulting rule directly: attempt the
insert, catch `IntegrityError`, re-read the winner — the database is the
arbiter, not your code.

That rule is correct and this ADR does not touch it. What it adds is a
narrower question: for a request whose idempotency key has already been
seen recently by the *same process*, is a database round trip the cheapest
way to find that out? Not always — a local, in-memory check can answer
"definitely not a duplicate I've seen" or "definitely a duplicate I've
seen" in a single dictionary lookup, with no network hop. The interesting
failure mode is what happens when that local answer is wrong, and this ADR
exists mainly to bound that failure mode precisely, not to sell the fast
path as a free win.

## Decision

Two new pieces, both inert until something chooses to use them:

- `app.idempotency.protocol.IdempotencyIndex` — an abstract `Protocol`
  stating the contract any idempotency check must satisfy: calling
  `check_and_insert(key, request_hash)` twice with the same arguments must
  return the "already seen, same body" outcome the second time, and must
  never insert twice. This is the `f(f(x)) = f(x)` requirement stated
  precisely. The protocol has no implementation and no opinion about what
  backs it — Postgres, memory, or something else.
- `app.idempotency.local_index.ShardedLocalIdempotencyIndex` — one
  concrete, single-process implementation: N shards, each a plain `dict`,
  with `check_and_insert` doing exactly one atomic `dict.setdefault` per
  attempt.

The load-bearing rule, stated as plainly as ADR 0002's own: **this index is
valid only within a single OS process. It must only ever be used as a
pre-filter that can skip a database round trip for a key it has already
locally recorded — never as the thing that decides the final outcome.** The
UNIQUE constraint on `IdempotencyKey.key` remains, unconditionally, the only
mechanism that decides whether a transaction is created. Nothing in this
ADR asks `post_transaction` to be rewritten, and nothing in it is wired
into `app/domain/ledger.py`. Whether to use this index there at all is left
to whoever implements that function, exactly as CLAUDE.md already reserves
that decision to them.

## Consequences

**Good**

- Near-zero-latency rejection of a duplicate that lands on the same
  process — directly useful against a retrying client, the exact scenario
  `loadtest/locustfile.py`'s `IdempotentRetryUser` already exercises.
- Adds no contention point of its own: sharding by key hash means a
  thundering herd against one key still only serializes within one shard's
  dictionary, and `dict.setdefault` is fast.
- Zero footprint in `app/domain/` or `app/models/` — both stay exactly as
  written.

**Bad, stated with the same weight as the Good above**

- **Zero correctness across more than one process.** The moment this
  service runs as more than one process or pod — the ordinary shape for
  anything actually operating at the volumes ADR 0004 was written
  against — two requests landing on two different processes each see "not
  present" locally, both pass the local check, and both attempt the
  insert. This is the exact write-skew class ADR 0002 exists to eliminate,
  recurring here for idempotency instead of a balance read. It stays safe
  only because the database constraint downstream is still unconditionally
  authoritative: the local index can produce a wrong *pass-through*
  decision, and the worst that costs is a redundant
  `IntegrityError`-and-retry cycle already handled by the existing
  post-transaction logic — it can never produce a wrong *final* result.
- **Making it correct across processes needs a shared store** — Redis
  `SETNX` or equivalent. Not adopted here: CLAUDE.md is explicit that new
  infrastructure isn't added without being asked. If cross-process
  correctness for this fast path is ever actually wanted, that is a new
  ADR that has to relitigate the no-new-infra rule out loud, not a quiet
  upgrade folded into this one.
- **Unbounded memory growth** if entries are never evicted. No eviction is
  implemented. Eviction, in turn, would create a false negative — an
  evicted key looks "new" again to a process that has genuinely seen it —
  which is a second, independent reason this can never be treated as sole
  authority, on top of the cross-process gap above.
- **"Lock-free" is an informal description, not a literature-accurate
  one.** No explicit lock object appears in this code, but its correctness
  rests on CPython's GIL making a single `dict.setdefault` call atomic —
  not on a compare-and-swap structure in the formal lock-free sense. This
  does not hold under a no-GIL (PEP 703) build without further work, and
  the implementation's docstring says so rather than overclaiming.

## Alternatives rejected

**Redis-backed shared index.** Would close the cross-process gap entirely
and is the standard production answer. Rejected here as unrequested new
infrastructure per CLAUDE.md — the honest answer if this fast path is ever
needed for real, not the answer for this exercise.

**Leave idempotency exactly as ADR 0002 left it, with no local layer.**
Still fully correct on its own; nothing about ADR 0002 is deficient. The
local layer here is an addition for the specific case this project wants
to exercise (an in-process, high-throughput check under load), not a fix
to a gap in the existing design.

**`multiprocessing.shared_memory` with real atomics.** Would extend
coverage to multiple processes sharing one host, but not across the
separate containers Docker Compose already gives each service — the added
complexity doesn't buy correctness at the boundary that actually matters
here.
