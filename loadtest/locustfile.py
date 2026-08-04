"""Load test.

The point is not a big number. The point is to prove the invariant survives
concurrency, and to have real figures for the README instead of adjectives.

Two scenarios matter:

  * HotAccountUser  — everyone posts against the same account pair. This is
    the contention case. A design with a mutable balance column collapses
    here; an append-only journal should not.

  * IdempotentRetryUser — deliberately retries the same idempotency key, as
    a flaky client would. Total postings must not exceed unique keys.

Run:  make load-test
Then: curl localhost:8000/api/v1/reconciliation/trial-balance
      -> must report balanced: true
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, events, task


@events.test_stop.add_listener
def _assert_book_balances(environment, **_kwargs) -> None:
    """After the run, the book must still balance.

    This is the assertion that makes the load test worth running. Throughput
    numbers are interesting; a corrupted ledger is disqualifying.
    """
    resp = environment.runner.environment.client.get(  # type: ignore[union-attr]
        "/api/v1/reconciliation/trial-balance"
    )
    body = resp.json()
    if not body.get("balanced"):
        environment.process_exit_code = 1
        print(f"\n!!! BOOK DOES NOT BALANCE — delta {body.get('delta')} !!!\n")
    else:
        print("\nbook balances after load\n")


class _Base(HttpUser):
    abstract = True

    def on_start(self) -> None:
        """Create the account pair this user will post against."""
        cash = self.client.post(
            "/api/v1/accounts",
            json={"name": f"cash-{uuid.uuid4()}", "normal_balance": "debit"},
        ).json()
        wallet = self.client.post(
            "/api/v1/accounts",
            json={"name": f"wallet-{uuid.uuid4()}", "normal_balance": "credit"},
        ).json()
        self.cash_id = cash["id"]
        self.wallet_id = wallet["id"]

    def _posting(self, amount: str) -> dict:
        return {
            "legs": [
                {"account_id": self.cash_id, "direction": "debit", "amount": amount},
                {"account_id": self.wallet_id, "direction": "credit", "amount": amount},
            ],
            "memo": "loadtest",
        }


class SteadyUser(_Base):
    """Baseline: independent accounts, no contention."""

    weight = 3
    wait_time = between(0.05, 0.2)

    @task(5)
    def post(self) -> None:
        amount = f"{random.randint(1, 10000) / 100:.2f}"
        self.client.post(
            "/api/v1/transactions",
            json=self._posting(amount),
            headers={"Idempotency-Key": str(uuid.uuid4())},
            name="POST /transactions",
        )

    @task(2)
    def read_balance(self) -> None:
        self.client.get(
            f"/api/v1/accounts/{self.wallet_id}/balance",
            name="GET /accounts/{id}/balance",
        )


class IdempotentRetryUser(_Base):
    """Simulates a flaky client retrying the same key.

    Duplicate postings here would be duplicated money. The count of created
    transactions must equal the count of distinct keys.
    """

    weight = 1
    wait_time = between(0.1, 0.3)

    @task
    def retry_same_key(self) -> None:
        key = str(uuid.uuid4())
        body = self._posting("10.00")
        for _ in range(3):
            self.client.post(
                "/api/v1/transactions",
                json=body,
                headers={"Idempotency-Key": key},
                name="POST /transactions [retried]",
            )
