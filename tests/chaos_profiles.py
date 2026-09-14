"""Chaos profiles for exercising app.idempotency under simulated faults.

Two different numbers get conflated easily here, so they're kept explicit
as separate fields: `scale_exponent` names which order-of-magnitude
scenario a profile represents (matching docs/THERMODYNAMIC_CONSTRAINTS.md),
while `thundering_herd_size` is the count of calls actually executed. For
exponents 5 and 6, `thundering_herd_size` is deliberately capped well below
a literal 10**5/10**6 so the suite finishes in seconds rather than minutes —
this module does not pretend to run a literal million calls. See
docs/THERMODYNAMIC_CONSTRAINTS.md for how the full range up to the 10**12
partitioning ceiling is represented analytically instead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationChaosProfile:
    """One chaos scenario: fault rate, jitter, and load for a given scale."""

    scale_exponent: int
    drop_rate: float
    jitter_ms_range: tuple[int, int]
    thundering_herd_size: int
    seed: int | None = None


_PROFILES: dict[int, SimulationChaosProfile] = {
    2: SimulationChaosProfile(2, 0.05, (0, 5), 10**2, seed=2),
    3: SimulationChaosProfile(3, 0.05, (0, 5), 10**3, seed=3),
    4: SimulationChaosProfile(4, 0.10, (0, 5), 10**4, seed=4),
    5: SimulationChaosProfile(5, 0.10, (0, 5), 20_000, seed=5),  # capped, not 10**5
    6: SimulationChaosProfile(6, 0.15, (0, 5), 50_000, seed=6),  # capped, not 10**6
}


def profile_for_scale(exponent: int) -> SimulationChaosProfile:
    """Return the chaos profile for a given order-of-magnitude scenario."""
    try:
        return _PROFILES[exponent]
    except KeyError as exc:
        raise ValueError(
            f"no chaos profile for scale exponent {exponent}; defined range "
            f"is {min(_PROFILES)}-{max(_PROFILES)}"
        ) from exc
