# Working agreement

Read this before doing anything in this repository.

## What this project is for

This is a learning project. The owner is a game-engine developer moving into
backend fintech work, and is deliberately new to production Python. The
purpose of the repo is for **the owner to learn by writing the hard parts
themselves**. A finished repo that the owner does not understand is a
failure, not a success.

Optimise for the owner's understanding, not for closing tickets quickly.

## Division of labour

**You may write, without asking:**

- Configuration, tooling, CI, Dockerfiles, Makefile targets
- Alembic migration scaffolding (the owner reviews the generated SQL)
- Type annotations, docstrings, comments on existing code
- Test *fixtures* and *harnesses* — plumbing, not assertions
- Debugging output, logging statements, throwaway scripts

**You must NOT write unless explicitly asked in that message:**

- Anything in `app/domain/` — this is the owner's work
- Anything in `app/models/` — this is the owner's work
- The `NotImplementedError` route bodies in `app/api/v1/`
- New assertions in `tests/test_ledger_domain.py` or
  `tests/test_concurrency.py` — these are the specification and must not be
  weakened or rewritten to accommodate an implementation

If the owner asks "how do I do X" about one of these, **explain the
approach; do not produce the implementation.** If they want the code they
will say "write it".

## Never do this

- Do not modify a test to make it pass. If a test seems wrong, say so and
  explain why; do not change it unilaterally.
- Do not add a `balance` column, a `status` column on transactions, or any
  UPDATE path to the journal. See `docs/adr/0001-immutable-journal.md`.
- Do not use `float` for money anywhere. `Decimal` in Python,
  `NUMERIC(20,4)` in Postgres.
- Do not implement idempotency as SELECT-then-INSERT. Constraint-arbitrated
  only. See `docs/adr/0002-isolation-levels.md`.
- Do not run migrations on application startup.
- Do not add Redis, Kafka, Celery, or any new infrastructure dependency
  without being asked. Resume-driven architecture is a negative signal.
- Do not refactor code you were not asked to touch.

## How to work

**Scope tightly.** Change the files you were asked about and nothing else.
State what you are about to touch before touching it.

**Plan before editing.** For anything non-trivial, describe the approach and
wait for agreement. The owner explicitly prefers reviewing a plan over
reviewing a large diff.

**One logical change per commit.** Do not batch unrelated edits.

**Explain the why.** When you make or suggest a decision, give the
reasoning, including what you rejected. The owner is trying to learn to make
these calls without you.

**Say when you are unsure.** A flagged uncertainty is more useful than a
confident guess. If a concurrency question depends on isolation semantics
you are not sure about, say so.

## Review mode

When asked to review the owner's code, be genuinely critical. Look for:

- Race conditions and check-then-act patterns
- Missing database constraints where an application check is being relied on
- Transaction boundary errors — commits inside domain logic, sessions
  poisoned by a caught `IntegrityError` without a SAVEPOINT
- `float` contamination in money paths
- Naive `datetime` objects (`datetime.utcnow()` is always a bug here)
- N+1 queries, OFFSET pagination, unbounded result sets
- Anything that mutates the journal

Do not soften the review. Praise nothing that is merely adequate.

## Architecture constraints

Dependencies point one way only:

```
app/api/  ->  app/domain/  ->  app/models/  ->  PostgreSQL
```

`app/domain/` must never import from `app/api/`. Domain functions never
commit — the caller owns the transaction boundary. Domain code raises the
exceptions in `app/domain/errors.py`, never bare `ValueError`.

## The four invariants

Any change that violates one of these is wrong, regardless of what was asked:

1. Every transaction balances — `sum(debits) == sum(credits)`, exactly.
2. Nothing is ever updated or deleted. Corrections are reversing entries.
3. Balances are derived from the journal. There is no balance column.
4. Postings are idempotent when an `Idempotency-Key` is supplied.

## Commands

Everything routes through the Makefile. Use these rather than raw docker or
pytest invocations.

    make up                # start postgres + api
    make migrate           # apply migrations
    make test              # full suite
    make test-unit         # fast, no database
    make test-integration  # database-backed, includes concurrency
    make lint typecheck    # ruff + mypy
    make psql              # interactive database shell
    make help              # everything else

## Where to read

- `docs/MILESTONES.md` — the build plan and current stage
- `docs/ARCHITECTURE.md` — layering and scaling path
- `docs/adr/` — decisions that are settled and not up for casual revision
- `app/domain/ledger.py` — docstring specs for the unimplemented functions
