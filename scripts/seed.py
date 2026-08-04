"""Seed a demo chart of accounts.

Run with:  make seed

Idempotent — safe to run repeatedly. Seed scripts that blow up on a second
run are a small, constant annoyance you should not inflict on yourself.

>>> Enable the marked block once your Account model exists. <<<
"""

from __future__ import annotations

import sys

from app.db import session_scope
from app.observability import configure_logging, get_logger

log = get_logger("seed")

# name -> (normal_balance, description)
#
# The shape of a real chart of accounts. Note that `user_wallet` is
# credit-normal: money you hold for a user is a liability to you, not an
# asset. Getting this backwards is the most common beginner error in ledger
# design, and it makes every balance sign wrong.
CHART: dict[str, tuple[str, str]] = {
    "platform_cash": ("debit", "Cash the platform actually holds — an asset"),
    "user_wallet": ("credit", "Balance owed to users — a liability"),
    "fee_revenue": ("credit", "Fees earned — income"),
    "reserve": ("debit", "Funds held back against chargebacks — an asset"),
    "payment_processor": ("debit", "In-flight funds at the PSP — an asset"),
    "chargeback_losses": ("debit", "Written-off losses — an expense"),
}


def main() -> int:
    configure_logging()

    with session_scope() as session:  # noqa: F841
        # ------------------------------------------------------------------
        # from app.models import Account
        #
        # existing = {a.name for a in session.query(Account).all()}
        # created = 0
        # for name, (normal, description) in CHART.items():
        #     if name in existing:
        #         continue
        #     session.add(
        #         Account(name=name, normal_balance=normal, currency="USD")
        #     )
        #     created += 1
        #     log.info("account_created", name=name, normal_balance=normal)
        # log.info("seed_complete", created=created, skipped=len(existing))
        # return 0
        # ------------------------------------------------------------------
        log.warning("seed_skipped", reason="Account model not yet defined")
        return 0


if __name__ == "__main__":
    sys.exit(main())
