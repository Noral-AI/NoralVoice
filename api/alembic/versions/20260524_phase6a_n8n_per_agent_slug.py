"""phase 6a: per-agent n8n automation slug

Adds ``workflows.n8n_automation_slug`` so each NoralVoice workflow
(agent) can route its automation events to a dedicated n8n webhook
namespace instead of every agent sharing one URL per event type.

When set, the slug becomes part of the webhook path:
``/webhook/noralvoice/{slug}/{event}``. When NULL, the legacy
unnamespaced path is used. This keeps existing single-agent setups
working without migration of n8n workflows.

The column is nullable + lowercase-dash-only by check constraint so
slugs map cleanly to URL path segments. Length is capped at 64 to
keep URLs short and to prevent abuse.

A partial index covers the common case where most rows have NULL slug
(opt-in field) — used by future per-slug lookups.

Revision ID: b8d2f3a1c7e5
Revises: c5d7e9f1a2b3
Create Date: 2026-05-24 09:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8d2f3a1c7e5"
down_revision: Union[str, None] = "c5d7e9f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("n8n_automation_slug", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_workflows_n8n_automation_slug_format",
        "workflows",
        "n8n_automation_slug IS NULL OR "
        "n8n_automation_slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
    )
    op.create_index(
        "ix_workflows_n8n_automation_slug",
        "workflows",
        ["n8n_automation_slug"],
        unique=False,
        postgresql_where=sa.text("n8n_automation_slug IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_workflows_n8n_automation_slug", table_name="workflows")
    op.drop_constraint(
        "ck_workflows_n8n_automation_slug_format",
        "workflows",
        type_="check",
    )
    op.drop_column("workflows", "n8n_automation_slug")
