"""api_keys: add delegation_capable flag

Adds ``api_keys.delegation_capable`` so NoralVoice can opt specific keys
into honoring NoralOS-asserted user identity in the ``X-Noralos-Actor-User-*``
request headers.

When the flag is true and the inbound request carries those headers,
auth resolves ``current_user`` by JIT-provisioning a user with
``provider_id="noralos:<userId>"`` — the same path the existing browser
SSO flow uses (``api/services/auth/noral_sso.py``). This makes
agent-created entities (workflows, etc.) owned by the human user instead
of the shared service-key creator.

Default is ``false``, so existing keys are unaffected. Flip per key with
an admin script after deploy.

A partial index covers the small set of delegation-capable keys for fast
auditing queries; the vast majority of rows stay outside the index.

Revision ID: d3f1a8c2e604
Revises: b8d2f3a1c7e5
Create Date: 2026-05-26 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d3f1a8c2e604"
down_revision: Union[str, None] = "b8d2f3a1c7e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "delegation_capable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_api_keys_delegation_capable",
        "api_keys",
        ["delegation_capable"],
        unique=False,
        postgresql_where=sa.text("delegation_capable = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_delegation_capable", table_name="api_keys")
    op.drop_column("api_keys", "delegation_capable")
