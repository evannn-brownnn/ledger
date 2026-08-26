# Working state

Operational state that is **not** derivable from the code or git history:
what is in flight, what is known-broken, and which failures are expected
rather than regressions.

Tracked in the repo deliberately. Assistant memory is per-machine, and this
project is developed on two (WSL2 desktop, native Ubuntu laptop) — anything
worth remembering has to live here or it does not survive the switch.

Keep it short. Delete entries as they stop being true. Last updated
2026-08-26.

## Branches

| Branch | Contains | State |
|---|---|---|
| `main` | infra, docs, schema migrations | green on lint/typecheck, see "expected red" below |
| `wip/transactions-composite-pk` | `Transaction` PK change + the FK removals chosen alongside it | migration finished and verified; ready to merge |

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
