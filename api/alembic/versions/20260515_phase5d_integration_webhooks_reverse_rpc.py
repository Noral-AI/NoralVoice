"""phase 5d: reverse_rpc_url + reverse_rpc_secret on integration_webhooks

Adds two nullable columns to ``integration_webhooks`` so a NoralOS
plugin that registers an outbound webhook with NoralVoice can ALSO
publish its reverse-RPC callback URL + secret. When a NoralVoice
workflow Agent node invokes a tool with the ``noralos://`` URL scheme,
the executor looks up the row with a non-null ``reverse_rpc_url`` for
the run's organization and POSTs there with an HMAC-SHA256 signature
in the ``X-Noralos-Signature`` header.

The columns are nullable + per-row to keep the schema simple — a plugin
typically registers one webhook (`run.completed`) and stamps the reverse
URL onto that same row. Other event-type rows (if any) leave the columns
NULL. ``get_reverse_rpc_for_org`` picks the first non-null row.

Per the Phase 5 plan: do NOT reuse the outbound ``secret`` field for the
reverse direction; reverse-RPC needs its own secret so a leak of one
doesn't compromise the other.

Revision ID: c5d7e9f1a2b3
Revises: a1b2c4d6e8f0
Create Date: 2026-05-15 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c5d7e9f1a2b3"
down_revision: Union[str, None] = "a1b2c4d6e8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "integration_webhooks",
        sa.Column("reverse_rpc_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "integration_webhooks",
        sa.Column("reverse_rpc_secret", sa.String(length=64), nullable=True),
    )
    # Partial index: only rows that actually carry a reverse-RPC config.
    # ``get_reverse_rpc_for_org`` filters by ``organization_id`` +
    # ``reverse_rpc_url IS NOT NULL``; this index makes that fast without
    # bloating the index on the no-reverse-RPC rows (the common case).
    op.create_index(
        "ix_integration_webhooks_reverse_rpc_org",
        "integration_webhooks",
        ["organization_id"],
        unique=False,
        postgresql_where=sa.text("reverse_rpc_url IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_webhooks_reverse_rpc_org",
        table_name="integration_webhooks",
    )
    op.drop_column("integration_webhooks", "reverse_rpc_secret")
    op.drop_column("integration_webhooks", "reverse_rpc_url")
