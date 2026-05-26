"""api_keys: add key_plaintext for re-copy after creation

Adds ``api_keys.key_plaintext`` so the UI can let an org admin re-copy a
previously-issued key. Without it, the plaintext is unrecoverable once
the post-creation dialog is dismissed (only ``key_hash`` is stored).

This is a deliberate weakening of the hash-only pattern: anyone with DB
read access can now read every org's keys. The product owner accepted
that trade-off to make day-to-day key handout less painful.

Existing rows stay NULL because we never persisted their plaintext.
Those keys remain valid for auth (hash lookup is unchanged) but cannot
be re-revealed — the UI hides the reveal button when this column is
NULL.

Revision ID: e4a2b9d3f715
Revises: d3f1a8c2e604
Create Date: 2026-05-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e4a2b9d3f715"
down_revision: Union[str, None] = "d3f1a8c2e604"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("key_plaintext", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "key_plaintext")
