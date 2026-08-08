"""add provider, last_four and rotated_at to external_credentials

Additive only, and deliberately so: this runs against a live database that is
serving calls, so every column is nullable with no default backfill and no
existing row is rewritten. Encrypting the existing plaintext rows is a separate,
fenced migration that requires a verified backup first (plan §10.4).

- provider   which upstream the credential authenticates against ("elevenlabs").
             NULL for the webhook credentials this table originally held, which
             is why it is nullable rather than defaulted.
- last_four  last four characters of the secret, in the clear, so the settings
             UI can show which key is installed without the read path ever
             decrypting it.
- rotated_at when the secret was last replaced. Distinct from updated_at, which
             also moves when only the name or description changes.

Revision ID: a1c4e7b920f3
Revises: e4a2b9d3f715
Create Date: 2026-08-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e7b920f3"
down_revision: Union[str, None] = "e4a2b9d3f715"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "external_credentials",
        sa.Column("provider", sa.String(), nullable=True),
    )
    op.add_column(
        "external_credentials",
        sa.Column("last_four", sa.String(length=4), nullable=True),
    )
    op.add_column(
        "external_credentials",
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_external_credentials_provider",
        "external_credentials",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_credentials_provider", table_name="external_credentials")
    op.drop_column("external_credentials", "rotated_at")
    op.drop_column("external_credentials", "last_four")
    op.drop_column("external_credentials", "provider")
