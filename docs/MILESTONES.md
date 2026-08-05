# Milestones

The build plan. Work through these roughly in order — later ones assume
earlier ones are done.

"Owner" milestones are yours to write per [CLAUDE.md](../CLAUDE.md)'s
division of labour — domain logic, models, and the two spec test files.
"Infra" milestones are tooling, docs, and ops work an AI assistant can build
directly.

**Do not confuse these numbers with the scaling stages in
[ARCHITECTURE.md](ARCHITECTURE.md).** That table (stage 1 through 6)
describes architectural readiness levels — most of which stay
design-only in this project rather than built. A milestone can *touch* a
scaling stage without being numbered the same; the two axes are unrelated,
and reusing numbers between them is what caused earlier drafts of this
project to describe snapshots as both "milestone 5" and "milestone 7" in
different places. Fixed here by not reusing them at all.

| # | Milestone | Owner | Status | Scaling stage(s) touched |
|---|---|---|---|---|
| 0 | Scaffolding: infra layer, CI, ADRs 0001–0002 | infra | done | stage 1 (implicit) |
| 1 | Models + domain core — `Account`, `Transaction`, `TransactionLine`, `IdempotencyKey`, `AuditEvent`; `post_transaction`, `reverse_transaction`, `balance`, `trial_balance`, `account_statement`; the 4 stub route bodies | **owner** | not started | stage 1 |
| 1.5 | ADR 0003 — partitioning primary-key shape + snapshot design, decided alongside milestone 1 so the model PK doesn't need retrofitting | **owner + infra** | not started | stages 3, 4 |
| 2 | API-level HTTP test suite | infra | not started | — |
| 3 | Concurrency proof — the three non-skipped tests in `tests/test_concurrency.py`; optional `withdraw()` / `InsufficientFunds` stretch | **owner** | not started | stage 1 |
| 4 | Service-to-service API-key auth | infra | not started | — |
| 5 | Trial-balance reconciliation job + alerting | infra | not started | — |
| 6 | Pre-commit, dependency hygiene, Docker build fix | infra | done | — |
| 7 | Docs closure — this file finalized, load-test numbers recorded, diagrams reconciled | infra | not started | — |
| 8 (stretch, not default scope) | Any of: read replicas, monthly partitions, balance snapshots, sharded counters, outbox table | owner's call | not started | stages 2–6 |

## Notes

- **Milestone 1 is the gate.** Almost everything past it depends on real
  models and a working domain layer existing. There's no way to shortcut
  this one — see `app/domain/ledger.py` and `app/models/__init__.py` for the
  full spec of what's expected.
- **Milestone 1.5 has to happen alongside 1, not after.** The partitioning
  decision constrains the `Transaction`/`TransactionLine` primary key
  (`app/models/__init__.py`'s own docstring: "design for it now"). Deciding
  it after the models are written means rewriting them.
- **Milestone 3's fourth test is deliberately skipped**, not part of the
  original spec — `test_read_modify_write_cannot_overdraw` waits on a
  `withdraw()` / `InsufficientFunds` path that doesn't exist yet. Attempting
  it is optional, not required to call milestone 3 done.
- **Milestone 8 is out of default scope.** Docker Compose + the existing CI
  is the deployment target for this project; standing up read replicas or a
  sharded counter scheme is design work worth doing on paper
  (`docs/ARCHITECTURE.md` already sketches it) but not infrastructure worth
  building without a reason. Resume-driven architecture is a negative
  signal — see `CLAUDE.md`.
