"""A single-process idempotency fast-path, decoupled from the domain layer.

`protocol.py` is an abstract contract only. `app/domain/ledger.py`'s
`post_transaction` is untouched by this package and free to implement this
Protocol against Postgres, use the reference implementation in
`local_index.py`, or ignore this package entirely — that choice belongs to
whoever writes that function, per CLAUDE.md. See
`docs/adr/0005-in-process-idempotency-index.md` for the decision and, most
importantly, its scope limits.
"""
