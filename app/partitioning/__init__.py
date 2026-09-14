"""Partition-width policy for the ledger journal.

This package is consulted by future migration tooling and ops runbooks — it
is not imported by `app/api` or `app/domain` at request time, and nothing
here touches a database connection. See
`docs/adr/0004-dynamic-partition-granularity.md` for the decision this
implements.
"""
