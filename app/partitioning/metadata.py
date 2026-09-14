"""Row-count-to-partition-width policy.

See `docs/adr/0004-dynamic-partition-granularity.md` for the decision this
encodes. Nothing here talks to Postgres: the caller is responsible for
producing a row-count estimate (`pg_class.reltuples`, an actual `COUNT(*)`,
or a running counter) and this module answers a pure question about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PartitionInterval = Literal["none", "monthly", "weekly", "daily", "hourly"]


@dataclass(frozen=True)
class RadixPartitionMetadata:
    """One tier of the partition-width policy.

    `row_count_threshold` is inclusive: a table at exactly this many rows
    already uses `interval`, not the previous tier's.
    """

    row_count_threshold: int
    interval: PartitionInterval
    rationale: str


# Ordered ascending by threshold — interval_for_row_count relies on that.
RADIX_THRESHOLDS: tuple[RadixPartitionMetadata, ...] = (
    RadixPartitionMetadata(
        row_count_threshold=0,
        interval="none",
        rationale=(
            "Postgres holds low hundreds of thousands of rows in one table "
            "with no planner or autovacuum penalty; partitioning below the "
            "next tier buys nothing."
        ),
    ),
    RadixPartitionMetadata(
        row_count_threshold=10**6,
        interval="monthly",
        rationale="Where partition overhead starts paying for itself.",
    ),
    RadixPartitionMetadata(
        row_count_threshold=10**8,
        interval="weekly",
        rationale="A monthly partition here is too large for its indexing benefit.",
    ),
    RadixPartitionMetadata(
        row_count_threshold=10**9,
        interval="daily",
        rationale="A weekly partition here is too large for its indexing benefit.",
    ),
    RadixPartitionMetadata(
        row_count_threshold=10**10,
        interval="hourly",
        rationale="The finest interval this policy offers.",
    ),
)

# Not a tier with a finer interval — a documented boundary. Past this,
# no partition width fixes it on one Postgres instance; the honest next
# step is horizontal sharding, which is a separate, deliberate
# infrastructure decision this policy does not make. See ADR 0004.
PARTITION_CEILING = 10**12


def interval_for_row_count(row_count: int) -> PartitionInterval:
    """Return the partition interval this policy assigns at `row_count` rows.

    Raises ValueError for a negative count, and for a count past
    `PARTITION_CEILING` — deliberately, rather than silently returning
    "hourly" as if it were still a valid answer past the point ADR 0004
    says it stops being one.
    """
    if row_count < 0:
        raise ValueError(f"row_count must be non-negative, got {row_count}")
    if row_count > PARTITION_CEILING:
        raise ValueError(
            f"row_count {row_count} exceeds the {PARTITION_CEILING} ceiling "
            "this policy documents (see docs/adr/0004-dynamic-partition-"
            "granularity.md) — single-instance time-range partitioning is "
            "not a valid answer here; this is not a bug to clamp around."
        )

    interval: PartitionInterval = RADIX_THRESHOLDS[0].interval
    for tier in RADIX_THRESHOLDS:
        if row_count >= tier.row_count_threshold:
            interval = tier.interval
        else:
            break
    return interval
