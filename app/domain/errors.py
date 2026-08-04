"""Domain exceptions.

Domain code raises these. It does not know about HTTP. The API layer maps
them to status codes in `app/api/errors.py`.

Keeping this separation means your ledger logic stays testable without a
web framework, and could be reused by a worker or CLI unchanged.
"""

from __future__ import annotations


class LedgerError(Exception):
    """Base class. Everything below is a client-correctable condition."""

    code: str = "ledger_error"


class InvalidPosting(LedgerError):
    """Structurally invalid: too few legs, bad direction, bad amount."""

    code = "invalid_posting"


class UnbalancedTransaction(LedgerError):
    """Sum of debits != sum of credits. The cardinal sin."""

    code = "unbalanced_transaction"


class CurrencyMismatch(LedgerError):
    """Legs span multiple currencies, or use an unsupported one.

    Cross-currency movement is not a single transaction — it is two
    transactions plus an FX position. Rejecting it here keeps you honest.
    """

    code = "currency_mismatch"


class AccountNotFound(LedgerError):
    code = "account_not_found"


class TransactionNotFound(LedgerError):
    code = "transaction_not_found"


class AlreadyReversed(LedgerError):
    """A transaction may be reversed at most once."""

    code = "already_reversed"


class CannotReverseReversal(LedgerError):
    """Reversing a reversal is almost always a bug in the caller.

    If you genuinely need it, post a fresh correcting entry instead so the
    intent is explicit in the journal.
    """

    code = "cannot_reverse_reversal"


class IdempotencyKeyConflict(LedgerError):
    """Key reused with a different request body.

    This is a real client bug and must not silently return the original
    response — that would mask a mistake with financial consequences.
    """

    code = "idempotency_key_conflict"


class InsufficientFunds(LedgerError):
    """Only meaningful for accounts you have chosen to constrain.

    Note this check is a read-then-write and is therefore only safe under
    SERIALIZABLE isolation or an explicit lock. See docs/adr/0002.
    """

    code = "insufficient_funds"
