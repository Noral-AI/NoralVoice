"""add ElevenLabs columns across organizations, workflows, phone numbers and runs

Additive and prod-safe (plan §13 "Phase 1 — additive"). Every column is
nullable with no backfill, so the engine keeps serving while ElevenLabs-sourced
data starts landing alongside it. Nothing here drops or rewrites anything.

The one column that carries a constraint is
``workflow_runs.elevenlabs_conversation_id``, which is UNIQUE. That is the
idempotency key for ingestion: it is what makes replaying a webhook, or running
reconciliation across a window already ingested, a no-op instead of a duplicate
call. Created as a unique index rather than a table constraint so it can be
built CONCURRENTLY later if the table has grown by the time this ships.

Revision ID: b2d5f8a341c7
Revises: a1c4e7b920f3
Create Date: 2026-08-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2d5f8a341c7"
down_revision: Union[str, None] = "a1c4e7b920f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- organizations ------------------------------------------------
    op.add_column("organizations", sa.Column("name", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("status", sa.String(32), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("elevenlabs_workspace_id", sa.String(), nullable=True),
    )

    # --- workflows ----------------------------------------------------
    op.add_column(
        "workflows", sa.Column("elevenlabs_agent_id", sa.String(), nullable=True)
    )
    op.add_column(
        "workflows",
        sa.Column("elevenlabs_current_version", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_workflows_elevenlabs_agent_id", "workflows", ["elevenlabs_agent_id"]
    )

    # --- telephony_phone_numbers --------------------------------------
    op.add_column(
        "telephony_phone_numbers",
        sa.Column("elevenlabs_phone_number_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_telephony_phone_numbers_elevenlabs_phone_number_id",
        "telephony_phone_numbers",
        ["elevenlabs_phone_number_id"],
    )

    # --- workflow_runs ------------------------------------------------
    op.add_column(
        "workflow_runs",
        sa.Column("elevenlabs_conversation_id", sa.String(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("elevenlabs_agent_id", sa.String(), nullable=True),
    )
    op.add_column(
        "workflow_runs", sa.Column("duration_seconds", sa.Integer(), nullable=True)
    )
    op.add_column("workflow_runs", sa.Column("sentiment", sa.String(), nullable=True))
    op.add_column(
        "workflow_runs",
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # The idempotency key. Unique across the table; NULLs do not collide in
    # Postgres, so every existing engine run remains valid.
    op.create_index(
        "ix_workflow_runs_elevenlabs_conversation_id",
        "workflow_runs",
        ["elevenlabs_conversation_id"],
        unique=True,
    )
    op.create_index(
        "ix_workflow_runs_elevenlabs_agent_id",
        "workflow_runs",
        ["elevenlabs_agent_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_runs_elevenlabs_agent_id", table_name="workflow_runs"
    )
    op.drop_index(
        "ix_workflow_runs_elevenlabs_conversation_id", table_name="workflow_runs"
    )
    op.drop_column("workflow_runs", "transcript")
    op.drop_column("workflow_runs", "sentiment")
    op.drop_column("workflow_runs", "duration_seconds")
    op.drop_column("workflow_runs", "elevenlabs_agent_id")
    op.drop_column("workflow_runs", "elevenlabs_conversation_id")

    op.drop_index(
        "ix_telephony_phone_numbers_elevenlabs_phone_number_id",
        table_name="telephony_phone_numbers",
    )
    op.drop_column("telephony_phone_numbers", "elevenlabs_phone_number_id")

    op.drop_index("ix_workflows_elevenlabs_agent_id", table_name="workflows")
    op.drop_column("workflows", "elevenlabs_current_version")
    op.drop_column("workflows", "elevenlabs_agent_id")

    op.drop_column("organizations", "elevenlabs_workspace_id")
    op.drop_column("organizations", "status")
    op.drop_column("organizations", "name")
