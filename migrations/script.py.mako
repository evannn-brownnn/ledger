"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

REVIEW CHECKLIST — autogenerate is a draft, not an oracle:

  [ ] Does downgrade() actually reverse upgrade()? Test it.
  [ ] Any new index on a large table -> use postgresql_concurrently=True
      and set this migration non-transactional, or you lock writes.
  [ ] Adding a NOT NULL column to a populated table needs a server_default
      or a three-step deploy.
  [ ] Did autogenerate try to DROP something you meant to keep?
  [ ] Read the generated SQL: `alembic upgrade head --sql`
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
