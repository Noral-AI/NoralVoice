"""phase 7.5: external_actors table + attribution columns on user-authored tables

Adds the cross-system attribution layer specced in
``PARITY_AND_VISIBILITY_PLAN.md`` §3.1. Two pieces:

1. New ``external_actors`` table — append-only roster of every non-human
   identity (e.g. NoralOS agent) that has ever acted against this NoralVoice
   organisation. Looked up by ``(integration_id, external_actor_id)``.

2. Six nullable columns on each of the eight tables that today record a
   user-authored action (workflows, workflow_runs, campaigns,
   knowledge_base_documents, tools, telephony_configurations,
   workflow_recordings, embed_tokens):

       created_by_external_actor_id        uuid   null  references external_actors(id)
       created_by_external_run_id          uuid   null
       created_by_external_label           text   null
       last_modified_by_external_actor_id  uuid   null  references external_actors(id)
       last_modified_by_external_run_id    uuid   null
       last_modified_by_external_label     text   null

   All NULL means "human-authored via NoralVoice directly" — preserves
   existing rows exactly.

Pure additive — no breaking changes to the existing schema. Reverts cleanly
in ``downgrade()``.

Revision ID: d3f4e5b6c7a8
Revises: c5d7e9f1a2b3
Create Date: 2026-05-19 10:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d3f4e5b6c7a8"
down_revision: Union[str, None] = "c5d7e9f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The eight write-recording tables per PARITY_AND_VISIBILITY_PLAN §3.3, mapped
# to live tablenames. Keep this list in sync with
# ``api/services/auth/external_actor_events.py::ATTRIBUTED_TABLES``.
ATTRIBUTED_TABLES = (
    "workflows",
    "workflow_runs",
    "campaigns",
    "knowledge_base_documents",
    "tools",
    "telephony_configurations",
    "workflow_recordings",
    "embed_tokens",
)


def upgrade() -> None:
    # 1. external_actors roster table.
    op.create_table(
        "external_actors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("integration_id", sa.Text(), nullable=False),
        sa.Column("external_actor_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("display_kind", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "integration_id",
            "external_actor_id",
            name="uq_external_actors_integration_actor",
        ),
    )
    op.create_index(
        "ix_external_actors_last_seen",
        "external_actors",
        ["last_seen_at"],
        unique=False,
    )

    # 2. Six attribution columns on each user-authored table + FKs + per-table
    # indexes on the FK columns (so the UI's "Acted by → NoralOS agents" filter
    # can scan just the rows that carry attribution).
    for table in ATTRIBUTED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "created_by_external_actor_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "created_by_external_run_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column("created_by_external_label", sa.Text(), nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "last_modified_by_external_actor_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "last_modified_by_external_run_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "last_modified_by_external_label", sa.Text(), nullable=True
            ),
        )

        op.create_foreign_key(
            f"fk_{table}_created_by_external_actor",
            table,
            "external_actors",
            ["created_by_external_actor_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_last_modified_by_external_actor",
            table,
            "external_actors",
            ["last_modified_by_external_actor_id"],
            ["id"],
            ondelete="SET NULL",
        )

        # Partial index — most rows will have NULL attribution (human-authored
        # via NoralVoice direct). Skipping NULLs keeps the index small.
        op.create_index(
            f"ix_{table}_created_by_external_actor",
            table,
            ["created_by_external_actor_id"],
            unique=False,
            postgresql_where=sa.text(
                "created_by_external_actor_id IS NOT NULL"
            ),
        )


def downgrade() -> None:
    for table in ATTRIBUTED_TABLES:
        op.drop_index(
            f"ix_{table}_created_by_external_actor",
            table_name=table,
        )
        op.drop_constraint(
            f"fk_{table}_last_modified_by_external_actor",
            table,
            type_="foreignkey",
        )
        op.drop_constraint(
            f"fk_{table}_created_by_external_actor",
            table,
            type_="foreignkey",
        )
        op.drop_column(table, "last_modified_by_external_label")
        op.drop_column(table, "last_modified_by_external_run_id")
        op.drop_column(table, "last_modified_by_external_actor_id")
        op.drop_column(table, "created_by_external_label")
        op.drop_column(table, "created_by_external_run_id")
        op.drop_column(table, "created_by_external_actor_id")

    op.drop_index("ix_external_actors_last_seen", table_name="external_actors")
    op.drop_table("external_actors")
