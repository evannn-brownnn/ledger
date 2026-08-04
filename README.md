# Ledger Service

An immutable, double-entry ledger built with FastAPI, PostgreSQL and
SQLAlchemy 2.

## The invariants

1. Every transaction balances — `sum(debits) == sum(credits)`, exactly.
2. Nothing is ever updated or deleted. Corrections are reversing entries.
3. Balances are derived from the journal. There is no balance column.
4. Postings are idempotent when an `Idempotency-Key` is supplied.

## Quick start

```bash
cp .env.example .env
make up          # start postgres + api
make migrate     # apply migrations
make test        # run the suite
```

- API — http://localhost:8000
- Docs — http://localhost:8000/docs
- Metrics — http://localhost:8000/metrics

`make help` lists every command.

Full environment setup, including WSL2, is in [docs/SETUP.md](docs/SETUP.md).

## Layout

```
app/
  api/         routes, schemas, error mapping     — knows HTTP
    v1/ledger.py
    errors.py  domain exception -> status code
    schemas.py pydantic request/response contracts
    deps.py    session, idempotency key, body fingerprint
    health.py  liveness vs readiness
  domain/      ledger rules                       — knows nothing about HTTP
    ledger.py  << your work goes here
    errors.py  domain exceptions
  models/      SQLAlchemy tables                  << your work goes here
  config.py    env-driven settings, validated at startup
  db.py        engine, session scope, SERIALIZABLE retry helper
  observability.py  structured logs, request IDs, prometheus metrics
  main.py      app factory

migrations/    alembic
tests/         spec suite + concurrency suite
docs/          architecture, milestones, ADRs
loadtest/      locust
```

## Status

The infrastructure is complete and runnable. The ledger logic is not
written — `app/domain/ledger.py` and `app/models/` are specified stubs.

`tests/test_ledger_domain.py` and `tests/test_concurrency.py` are the
executable specification. They fail until you implement the domain. That is
the intended starting state.

Work through [docs/MILESTONES.md](docs/MILESTONES.md) in order.

[CLAUDE.md](CLAUDE.md) defines the working agreement for AI assistance in this
repo — which files are hand-written, which are assisted, and which
invariants are not negotiable.

## Design decisions

- [ADR 0001 — immutable journal, derived balances](docs/adr/0001-immutable-journal.md)
- [ADR 0002 — SERIALIZABLE writes with retry](docs/adr/0002-isolation-levels.md)
- [Architecture overview](docs/ARCHITECTURE.md)
- [Diagrams](docs/DIAGRAMS.md) — layering, data model, the idempotency race,
  isolation and retry, scaling path

## Notes for whoever reads this repo

Two things are deliberate and worth noticing.

**Amounts are always positive**, with a separate `direction` column carrying
the sign. This makes the balanced-transaction invariant a plain sum
comparison and makes negative amounts unrepresentable rather than merely
discouraged.

**Uniqueness is enforced by database constraints, never by application
checks.** An application check is a read followed by a write and therefore
loses races. The idempotency-key insert and the reverse-once rule both rely
on UNIQUE indexes, with `IntegrityError` caught and resolved by re-reading
the winner.

## Load test results

<!-- Fill this in at milestone 7. Numbers beat adjectives. -->

| Scenario | Throughput | p50 | p99 | Notes |
|---|---|---|---|---|
| _to be measured_ | | | | |
