# Working state

Operational state that is **not** derivable from the code or git history:
what is in flight, what is known-broken, and which failures are expected
rather than regressions.

Tracked in the repo deliberately. Assistant memory is per-machine, and this
project is developed on two (WSL2 desktop, native Ubuntu laptop) — anything
worth remembering has to live here or it does not survive the switch.

Keep it short. Delete entries as they stop being true. Last updated
2026-08-27.

## Branches

| Branch | Contains | State |
|---|---|---|
| `main` | infra, docs, schema migrations | green on lint/typecheck, see "expected red" below |
| `wip/transactions-composite-pk` | two migrations: `0da3c0e77b31` (PK swap + FK removals) and `c0e492405f67` (constraint hardening) | both verified; ready to merge |

`c0e492405f67` adds the currency format CHECK on `accounts` and
`transactions`, the `(entity_type, entity_id, created_at)` index on
`audit_events`, `memo` NOT NULL at `varchar(255)`, and reorders the
`transaction_lines` PK to `(id, created_at)`.

`app/api/schemas.py` caps `memo` input at `max_length=255`, matching the
column exactly. Keep them in step — a memo the API accepts but the column
cannot hold is a 500 where a 422 belongs.

Both branches are pushed to `github.com/evannn-brownnn/ledger`. `main` and
`origin/main` are in sync. `feat/account-model` has been deleted — it was
fully contained in `main`.

## Known issues

**1 · Concurrency tests cannot build their schema.** *(plumbing, unfixed)*

`real_sessions` in `tests/test_concurrency.py` depends on `engine` but not
on `_schema`. `test_concurrency.py` sorts before `test_ledger_domain.py`,
so nothing has run the migrations by the time its fixtures execute, and
setup dies with `UndefinedTable: relation "accounts" does not exist`.

Adding `_schema` to the fixture's parameters fixes it. Left alone because
that file is a spec file under `CLAUDE.md`'s division of labour — a fixture
signature is plumbing, but it is the owner's call.

## Expected red — not regressions

`app/domain/ledger.py` is unimplemented, so every domain function raises
`NotImplementedError`. `make test` currently reports **21 failed, 11
passed, 4 errors**. That is milestone 1 being open, not breakage: the spec
tests were written first and fail until the domain is built.

The CI `test` job is therefore red, and will stay red until milestone 1
lands. The `lint` job (ruff + ruff format + mypy + lock drift) is green and
should stay that way.

Do not "fix" these by weakening the tests. See `CLAUDE.md`.

One gap worth knowing: CI runs `ruff check app tests`, so `migrations/` is
**not** linted, and it runs `alembic upgrade head` plus a full
`downgrade base` / `upgrade head` cycle but **not** `alembic check`. Model
drift against the migrations is caught at review time or not at all — run
`alembic check` by hand after touching `app/models/`.

## Migrations — two traps that have already cost time

**Autogenerate is a draft, and its blind spots are not obvious.** Writing
`c0e492405f67` it silently missed three things, each of which passes on an
empty table and fails on a populated one:

- **Primary key changes** — not detected at all. This is what left
  `0da3c0e77b31` with `pass` in both directions, and it missed the
  `transaction_lines` PK reorder too. Hand-write every PK change.
- **Backfills before `SET NOT NULL`** — it emitted the `ALTER` with no
  `UPDATE` in front of it.
- **`varchar` length narrowing** — `String` to `String(255)` came out as
  `existing_type=sa.VARCHAR()` with only nullability changed, leaving the
  column unbounded. `compare_type=True` did not catch it.

**Never edit a migration that is already applied.** Its `downgrade()` will
reference objects the database does not have, so `alembic downgrade` errors
and rolls back — leaving the version stamped at head, which makes the next
`upgrade` a no-op that looks like it succeeded. The order is: **downgrade
first, then edit, then upgrade.** `alembic check` is what catches it if you
get this wrong.

## Dependencies

Exact versions are pinned in `requirements.lock` (runtime) and
`requirements-dev.lock` (runtime + dev). CI and both Docker stages install
from them; the project itself installs `--no-deps` so pip cannot re-resolve
past the pins.

After editing dependencies in `pyproject.toml`:

```bash
make lock            # regenerate both files, commit them with the change
```

CI fails if the lockfiles are stale. uv treats an existing output file as
pinning preferences, so this only trips on real `pyproject.toml` changes,
not when a dependency publishes a new release.

One consequence worth knowing: the locks resolved to the newest versions
available, well past the floors in `pyproject.toml` (mypy 2.3 against a
`>=1.13` floor, pytest 9 against `>=8.3`). Newer mypy flagged three errors
in previously-clean code, fixed in `app/config.py` and
`app/observability.py`. Expect the same class of surprise on the next
deliberate upgrade.

## Environment

Two machines, same stack. Host tooling and setup for both is in
[SETUP.md](SETUP.md), including the native-Linux differences.

Everything runs through the Makefile — `make help`. Two notes that cost
time to rediscover:

- `docker compose run` writes files as **root**. Migrations generated via
  `make makemigration` come out root-owned and your editor cannot save
  them. `sudo chown $USER:` them after generating.
- `tests/conftest.py` reads `LEDGER_TEST_DATABASE_URL`, not
  `LEDGER_DATABASE_URL`, and *skips* every database-backed test when it
  cannot connect. The Makefile sets both from one variable so they cannot
  drift; a bare `pytest` still silently skips.
