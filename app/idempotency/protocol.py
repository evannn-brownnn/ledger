"""Abstract idempotency-check contract.

This module defines the contract only. It has no implementation and no
opinion about what backs it — Postgres, memory, or something else. See
`docs/adr/0005-in-process-idempotency-index.md` for the decision this
supports, and `app/domain/ledger.py`'s `post_transaction` docstring for the
actual, authoritative, database-constraint-based rule this repo runs on.
Implementing this Protocol is optional; whether `post_transaction` ever
calls into an implementation of it is a decision left entirely to whoever
writes that function.
"""

from __future__ import annotations

from typing import Literal, Protocol

IdempotencyOutcome = Literal["inserted", "duplicate_same", "duplicate_conflict"]


class IdempotencyIndex(Protocol):
    """Structural contract for a check-and-insert idempotency guard.

    f(f(x)) = f(x): calling `check_and_insert` twice with the same
    `(key, request_hash)` MUST return `"duplicate_same"` the second time,
    and MUST NOT insert a second record. A different `request_hash` under
    the same `key` MUST return `"duplicate_conflict"` and MUST NOT
    overwrite the first.

    Nothing about this Protocol implies where "inserted" state is held, or
    what happens across multiple processes — that is entirely a property of
    whichever implementation you are given. A Protocol only fixes
    behaviour, not mechanism.
    """

    def check_and_insert(self, key: str, request_hash: str) -> IdempotencyOutcome:
        """Atomically check `key` and record it if not already present.

        Returns:
            "inserted": `key` was not previously known to this index;
                recorded now.
            "duplicate_same": `key` was already known, with the same
                `request_hash`.
            "duplicate_conflict": `key` was already known, with a
                different `request_hash`.
        """
        ...
