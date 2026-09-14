"""Boundary tests for the volume-scaled partition-width policy.

Pure arithmetic, no database, no threads — every threshold in
docs/adr/0004-dynamic-partition-granularity.md can and should be checked
exhaustively rather than sampled.
"""

from __future__ import annotations

import pytest

from app.partitioning.metadata import PARTITION_CEILING, interval_for_row_count


@pytest.mark.parametrize(
    ("row_count", "expected"),
    [
        (0, "none"),
        (10**6 - 1, "none"),
        (10**6, "monthly"),
        (10**6 + 1, "monthly"),
        (10**8 - 1, "monthly"),
        (10**8, "weekly"),
        (10**8 + 1, "weekly"),
        (10**9 - 1, "weekly"),
        (10**9, "daily"),
        (10**9 + 1, "daily"),
        (10**10 - 1, "daily"),
        (10**10, "hourly"),
        (10**10 + 1, "hourly"),
        (PARTITION_CEILING, "hourly"),  # the ceiling itself is still valid
    ],
)
def test_interval_for_row_count_boundaries(row_count: int, expected: str) -> None:
    assert interval_for_row_count(row_count) == expected


def test_interval_for_row_count_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        interval_for_row_count(-1)


def test_interval_for_row_count_rejects_past_ceiling() -> None:
    with pytest.raises(ValueError, match="ceiling"):
        interval_for_row_count(PARTITION_CEILING + 1)
