"""A single-process reference implementation of IdempotencyIndex.

Read `docs/adr/0005-in-process-idempotency-index.md` before using this for
anything beyond the exercise it was written for. The one sentence that
matters: this index is correct only within one OS process, and must never
be treated as the thing that decides whether a transaction gets created —
only the UNIQUE constraint on `IdempotencyKey.key` (`app/models/ledger.py`)
does that.
"""

from __future__ import annotations

from app.idempotency.protocol import IdempotencyOutcome


class ShardedLocalIdempotencyIndex:
    """N-way sharded in-process idempotency guard.

    Each shard is a plain `dict[str, tuple[object, str]]`, storing a
    per-call marker alongside the request hash. Sharding by `hash(key) %
    shard_count` exists only to reduce false contention between unrelated
    keys under a thundering herd; it does nothing for correctness, which
    rests entirely on one atomic `dict.setdefault` call per attempt.

    The marker object is what makes "did *this* call win the race"
    answerable without a second, separately-racy check. A plain string
    comparison (`stored_hash == request_hash`) cannot tell "I just
    inserted this" apart from "someone else already inserted the same
    hash" — and worse, comparing the stored value's *identity* to the
    string you passed in is unreliable too, because CPython interns some
    string literals, so two unrelated calls built from the same literal
    can be the same object by coincidence. A fresh `object()` per call has
    no such coincidence: it is unique regardless of what request_hash
    contains, so `stored_marker is marker` reliably means "the tuple I
    passed to setdefault is the one that ended up in the dict."

    Correctness note (see ADR 0005): "lock-free" here is informal. No lock
    object appears in this code because CPython's GIL makes one dict
    method call atomic; this does not hold under a no-GIL (PEP 703) build
    without an explicit lock per shard.

    No eviction is implemented. Entries accumulate for the process's
    lifetime — a deliberately documented gap, not a silent omission; see
    ADR 0005's Consequences section for why eviction would trade this
    problem for a worse one (false negatives on evicted keys).
    """

    def __init__(self, shard_count: int = 16) -> None:
        if shard_count < 1:
            raise ValueError(f"shard_count must be >= 1, got {shard_count}")
        self._shard_count = shard_count
        self._shards: list[dict[str, tuple[object, str]]] = [
            {} for _ in range(shard_count)
        ]

    def _shard_for(self, key: str) -> dict[str, tuple[object, str]]:
        return self._shards[hash(key) % self._shard_count]

    def check_and_insert(self, key: str, request_hash: str) -> IdempotencyOutcome:
        shard = self._shard_for(key)
        marker: object = object()
        # The entire correctness argument is this one call: dict.setdefault
        # either installs (marker, request_hash) and returns it back to us,
        # or some earlier call already installed a different tuple and we
        # get that one instead — one atomic step, decided by the dict, not
        # by a check we perform beforehand.
        stored_marker, stored_hash = shard.setdefault(key, (marker, request_hash))
        if stored_marker is marker:
            return "inserted"
        if stored_hash == request_hash:
            return "duplicate_same"
        return "duplicate_conflict"
