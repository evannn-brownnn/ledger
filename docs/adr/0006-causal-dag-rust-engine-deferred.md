# ADR 0006 — Causal-DAG Rust engine: a deferred direction, not adopted

Status: deferred — recorded for future reconsideration, not adopted

## Context

A proposal (drafted externally, brought here for review) suggested
replacing the current stack — Python/FastAPI/SQLAlchemy/Alembic/Postgres —
with a from-scratch, containerized engine written in Rust: an in-memory-
first, append-only "causal DAG" model with asynchronous segmented log
rotation, plus a Python/NetworkX simulation harness kept structurally
decoupled from the Rust build. The stated goal is a core engine that could
eventually generalize beyond this ledger to other data-processing systems.

The intended path, as clarified during review, is to prototype and verify
the concept in Python first — against the same invariants this project
already holds itself to — then port the validated core engine logic to
Rust for latency, once the design is proven rather than merely asserted.
That sequencing (prototype, verify, then port the hot path) is a real and
common pattern; nothing about it is rejected here.

What this ADR does reject, for now, is starting that work. Two things
warranted deferral rather than adoption:

**Sequencing.** `docs/MILESTONES.md` milestone 1 — the domain layer this
whole ledger depends on — is not yet implemented. Every function in
`app/domain/ledger.py` still raises `NotImplementedError`. Starting a
second, larger engineering track before the first one is functional is a
scope risk this project doesn't need to take on.

**Unverified claims.** The original proposal's performance case rests on
assertions this repo has already learned, the hard way, not to accept
without verification — ADR 0003's original draft stated two confident
"Postgres cannot do X" claims that turned out false under actual testing
against a running Postgres 17 instance, corrected only once someone ran
the SQL. The Rust/causal-DAG proposal has the same shape of claim:

- **"True O(1) write performance"** holds for the ledger's *current*
  causal structure — `Transaction.reverses_id` is a single directed edge,
  capped at one per transaction by a UNIQUE constraint, so recording it is
  one pointer set at insert time. It is not yet demonstrated for the
  *general* causal DAG the proposal actually describes: a structure with
  multiple parent edges per node needs cycle detection and conflict
  ordering across concurrent writers, and that is not free by
  construction. The claim needs an actual algorithm and a complexity
  proof before it can stand as fact, not an assertion carried over from
  the drafting conversation.
- **"Write amplification"** was used loosely in the original proposal to
  describe ordinary B-tree update cost (O(log N) I/O per operation). The
  term properly refers to extra physical writes per logical write — SSD
  flash-translation-layer or LSM-tree compaction overhead — a different
  claim than the one being made.
- **The "traditional CRUD" contrast** describes a mutable-balance-column
  design, which this project rejected in ADR 0001 for exactly the lock-
  contention reasons cited. The current ledger does not have that
  problem, so the proposal's motivating comparison doesn't actually apply
  to what's being compared against. It's also worth noting Postgres's own
  MVCC model doesn't update rows in place — an `UPDATE` writes a new row
  version — which is structurally closer to append-only than the
  proposal's framing suggests.

**Is the current ledger already a causal DAG?** Not quite, and this ADR
states that precisely rather than loosely. The genuine shared property
with the proposal is the one ADR 0001 already decided on: immutable,
append-only, no in-place mutation, state derived rather than stored. That
is real and already true here. What's *not* yet true is a general
causal-dependency structure — the kind with multiple parent edges used to
order concurrent, otherwise-unrelated writers without a lock. The ledger's
only directed edge today is the single reversal link, which is a depth-one
forest, not a DAG in the sense the proposal means.

**A gap the original proposal didn't address:** durability. Postgres
currently provides ACID transactions, WAL-based crash recovery, and
replication, all without this project writing a line of code for them. An
in-memory-first engine takes on that responsibility itself. "Asynchronous
segmented log rotation to prevent OOM" answers memory pressure; it does
not answer what happens to in-flight state when the process dies mid-write,
or how a second replica stays consistent. That question has to be answered
by any future version of this proposal before it's adopted, not deferred
indefinitely.

## Decision

Not adopted now. The Python ledger's own milestones — the domain layer,
the concurrency proof, the rest of `docs/MILESTONES.md` — take priority.
This ADR exists so the direction and the reasoning around it are on the
record rather than lost, in case it's revisited later.

If revisited: the O(1)-under-generalization claim must be demonstrated
with a concrete algorithm and a benchmark run against this repo's own
ground truth before it is stated as fact anywhere in this repo's docs —
the same standard ADR 0003's amendment already established. Whether the
current ledger's shallow reversal structure is honest evidence for a
thesis claim depends entirely on what that claim actually asserts: general
append-only/immutable-architecture behavior, which this ledger already
demonstrates without overstatement, versus general causal-DAG behavior
(multi-parent ordering, concurrent-writer conflict resolution), which it
does not yet demonstrate and should not be described as demonstrating.

## Consequences

**Good**

- The idea and the reasoning against adopting it now are preserved on the
  record, in the same style as every other decision in this repo, instead
  of existing only in chat history.
- Current milestone work stays focused: no second engineering track opens
  before the first one — the domain layer this entire project depends
  on — is functional.
- Sets an explicit bar (algorithm + benchmark, not assertion) for what it
  would take to adopt this later, consistent with how ADR 0003 was
  actually corrected.

**Bad — open questions this ADR does not resolve**

- Durability strategy for an in-memory-first engine (crash recovery,
  replication) is unaddressed by the original proposal and unaddressed
  here.
- The causal-DAG generalization's complexity claims are unverified.
- "Abstract into any kind of data processing system" is a large,
  effectively unbounded scope on its own, independent of whether the
  Rust port itself is a good idea.
- Whether a future port targets this repo directly or a separate one is
  not decided here.

## Alternatives considered

**Adopt now, in parallel with the domain layer.** Rejected: the domain
layer isn't done, and running two large engineering tracks at once is a
bigger scope risk than either one alone.

**Discard the idea entirely.** Rejected: the owner wants the direction
and its reasoning preserved for later reconsideration and for the
thesis this project supports, not silently dropped.
