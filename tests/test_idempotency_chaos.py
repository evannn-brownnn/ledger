"""Chaos tests for the in-process IdempotencyIndex reference implementation.

Deliberately unmarked — no `concurrency` or `integration` pytest marker.
Despite resembling tests/test_concurrency.py in spirit, this suite never
touches a database; it only exercises app.idempotency.local_index in
memory. So it runs under both `make test-unit` and the full `make test`,
which is the point: the correctness argument here doesn't need Postgres to
exercise.

What this file does NOT prove: it is still one OS process, so it cannot
exercise the cross-process correctness gap documented in
docs/adr/0005-in-process-idempotency-index.md, no matter how high the scale
argument climbs. A passing run here says nothing about that gap.
"""

from __future__ import annotations

import pytest

from app.idempotency.local_index import ShardedLocalIdempotencyIndex
from tests.chaos_injector import FlakyIndexWrapper, thundering_herd
from tests.chaos_profiles import profile_for_scale


@pytest.mark.parametrize("exponent", [2, 3, 4, 5, 6])
def test_exactly_one_insert_under_chaos(exponent: int) -> None:
    """N concurrent callers, one key, one request_hash, injected drops.

    Exactly one caller may see "inserted"; every other attempt — including
    everything a dropped-and-retried caller sees along the way — must
    resolve to "duplicate_same", since every caller here uses the same
    request_hash. This is the in-process analogue of
    tests/test_concurrency.py's
    test_concurrent_same_idempotency_key_posts_once, minus the database.
    """
    profile = profile_for_scale(exponent)
    real_index = ShardedLocalIdempotencyIndex()
    flaky = FlakyIndexWrapper(real_index, profile)

    counts = thundering_herd(
        flaky,
        key=f"chaos-key-{exponent}",
        request_hash="same-request-body",
        n=profile.thundering_herd_size,
    )

    assert counts["inserted"] == 1, "exactly one caller may win the race"
    assert counts["duplicate_conflict"] == 0, "every caller used the same request_hash"
    assert counts["duplicate_same"] == profile.thundering_herd_size - 1


def test_conflicting_request_hash_is_never_silently_accepted() -> None:
    """A second caller with a different body under the same key must not
    be told it succeeded as-is — matching the real IdempotencyKeyConflict
    rule in app/domain/errors.py, even though this index never raises that
    exception itself (it only reports the outcome; raising is the caller's
    job).
    """
    index = ShardedLocalIdempotencyIndex()

    first = index.check_and_insert("shared-key", "body-a")
    second = index.check_and_insert("shared-key", "body-b")

    assert first == "inserted"
    assert second == "duplicate_conflict"
