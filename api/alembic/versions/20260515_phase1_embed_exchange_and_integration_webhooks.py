"""phase 1a: embed_exchange_tokens + integration_webhooks

Adds the two tables that back Phase 1's new endpoints:

  * ``embed_exchange_tokens`` — one-shot iframe-auth tokens issued by
    ``POST /api/v1/embed/exchange-token`` and consumed by
    ``GET /api/v1/embed/embed-login``.

  * ``integration_webhooks`` — outbound webhook registrations for
    ``run.completed`` / ``run.failed`` / ``campaign.progress``. The
    event_type is a real Postgres enum so the column is self-validating.

Stacks on top of the Phase 0 merge revision (``bf3a1e2c9d4f``). No
down-revision branching here — Phase 0 already collapsed the tree to a
single head.

Revision ID: a1b2c4d6e8f0
Revises: bf3a1e2c9d4f
Create Date: 2026-05-15 01:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c4d6e8f0"
down_revision: Union[str, None] = "bf3a1e2c9d4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INTEGRATION_WEBHOOK_EVENT_TYPE = "integration_webhook_event_type"
INTEGRATION_WEBHOOK_EVENTS = ("run.completed", "run.failed", "campaign.progress")


def upgrade() -> None:
    # ---------------- embed_exchange_tokens ----------------
    op.create_table(
        "embed_exchange_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("target_path", sa.String(length=2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_embed_exchange_tokens_token_hash"),
    )
    op.create_index(
        op.f("ix_embed_exchange_tokens_id"),
        "embed_exchange_tokens",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_embed_exchange_tokens_token_hash"),
        "embed_exchange_tokens",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_embed_exchange_tokens_organization_id"),
        "embed_exchange_tokens",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_embed_exchange_tokens_expires_at"),
        "embed_exchange_tokens",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_embed_exchange_tokens_org_expires",
        "embed_exchange_tokens",
        ["organization_id", "expires_at"],
        unique=False,
    )

    # ---------------- integration_webhooks ----------------
    # Postgres enum for event_type. ``alembic_postgresql_enum`` (hooked
    # in env.py) is responsible for creating the type up-front when it
    # sees the column. We just declare the column with sa.Enum and let
    # the auto-management hook do the CREATE TYPE.
    op.create_table(
        "integration_webhooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                *INTEGRATION_WEBHOOK_EVENTS,
                name=INTEGRATION_WEBHOOK_EVENT_TYPE,
            ),
            nullable=False,
        ),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_integration_webhooks_id"),
        "integration_webhooks",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_webhooks_organization_id"),
        "integration_webhooks",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_webhooks_event_type"),
        "integration_webhooks",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_integration_webhooks_org_event",
        "integration_webhooks",
        ["organization_id", "event_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_integration_webhooks_org_event", table_name="integration_webhooks"
    )
    op.drop_index(
        op.f("ix_integration_webhooks_event_type"),
        table_name="integration_webhooks",
    )
    op.drop_index(
        op.f("ix_integration_webhooks_organization_id"),
        table_name="integration_webhooks",
    )
    op.drop_index(
        op.f("ix_integration_webhooks_id"), table_name="integration_webhooks"
    )
    op.drop_table("integration_webhooks")
    sa.Enum(name=INTEGRATION_WEBHOOK_EVENT_TYPE).drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        "ix_embed_exchange_tokens_org_expires",
        table_name="embed_exchange_tokens",
    )
    op.drop_index(
        op.f("ix_embed_exchange_tokens_expires_at"),
        table_name="embed_exchange_tokens",
    )
    op.drop_index(
        op.f("ix_embed_exchange_tokens_organization_id"),
        table_name="embed_exchange_tokens",
    )
    op.drop_index(
        op.f("ix_embed_exchange_tokens_token_hash"),
        table_name="embed_exchange_tokens",
    )
    op.drop_index(
        op.f("ix_embed_exchange_tokens_id"), table_name="embed_exchange_tokens"
    )
    op.drop_table("embed_exchange_tokens")
