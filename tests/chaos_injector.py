"""Fault injection around an IdempotencyIndex.

Simulates dropped calls and jitter around a real index, and a bounded
concurrent thundering herd against one key — the tools
test_idempotency_chaos.py uses to check the reference implementation in
app/idempotency/local_index.py under load. This is in-process test
plumbing (CLAUDE.md permits this); it does not touch a database and does
not belong in the `app` package.
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from app.idempotency.protocol import IdempotencyIndex, IdempotencyOutcome
from tests.chaos_profiles import SimulationChaosProfile


class ChaosDroppedCallError(Exception):
    """Raised instead of delegating, to simulate a dropped call.

    Dropping happens before delegation to the wrapped index, which is what
    forces the *caller's* retry loop to run — the thing actually worth
    exercising, since the wrapped index's own `dict.setdefault` call is
    unconditionally atomic regardless of jitter or drops around it.
    """


class FlakyIndexWrapper:
    """Wraps a real IdempotencyIndex and injects drops and jitter.

    Structurally satisfies IdempotencyIndex: a caller that retries on
    ChaosDroppedCallError sees the same eventual outcomes as talking to the
    real index directly, just with added latency and occasional forced
    retries.
    """

    def __init__(
        self, wrapped: IdempotencyIndex, profile: SimulationChaosProfile
    ) -> None:
        self._wrapped = wrapped
        self._profile = profile
        self._rng = random.Random(profile.seed)

    def check_and_insert(self, key: str, request_hash: str) -> IdempotencyOutcome:
        if self._rng.random() < self._profile.drop_rate:
            raise ChaosDroppedCallError(f"simulated drop for key={key!r}")
        low, high = self._profile.jitter_ms_range
        time.sleep(self._rng.uniform(low, high) / 1000)
        return self._wrapped.check_and_insert(key, request_hash)


def thundering_herd(
    index: IdempotencyIndex,
    *,
    key: str,
    request_hash: str,
    n: int,
    workers: int = 64,
) -> dict[IdempotencyOutcome, int]:
    """Fire `n` concurrent check_and_insert calls at one key, count outcomes.

    `workers` bounds the real OS thread count regardless of `n` — a large
    `n` must not mean one OS thread per call, only that many calls
    processed through a pool of `workers` of them. Retries on a simulated
    drop rather than counting it as an outcome, matching how a real caller
    would treat a dropped response.
    """
    counts: dict[IdempotencyOutcome, int] = {
        "inserted": 0,
        "duplicate_same": 0,
        "duplicate_conflict": 0,
    }

    def _attempt(_: int) -> IdempotencyOutcome:
        while True:
            try:
                return index.check_and_insert(key, request_hash)
            except ChaosDroppedCallError:
                continue

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for outcome in pool.map(_attempt, range(n)):
            counts[outcome] += 1
    return counts
