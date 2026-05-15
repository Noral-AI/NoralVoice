"""merge three heads

Consolidates three concurrent migration branches that diverged in
April–May 2026 into a single head. This is a pure graph-merge: no schema
changes. Both ``upgrade()`` and ``downgrade()`` are no-ops.

The three heads being merged:
  * ``6499c608d0f6`` — add ``campaigns.logs`` column
  * ``cdcf9f65913b`` — add ``workflows.workflow_uuid`` column
  * ``f2e1d0c9b8a7`` — add ``plivo`` value to the workflow_run mode enum

A user / deployment may be at any one of those three heads (or upstream
of one of them). After running ``alembic upgrade head`` (singular — note
no ``s``), the database will be at this merge revision regardless of
which branch it came from. Future migrations stack on this revision so
the tree stays linear from here forward.

Revision ID: bf3a1e2c9d4f
Revises: 6499c608d0f6, cdcf9f65913b, f2e1d0c9b8a7
Create Date: 2026-05-15 00:00:00.000000

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "bf3a1e2c9d4f"
down_revision: Union[str, Sequence[str], None] = (
    "6499c608d0f6",
    "cdcf9f65913b",
    "f2e1d0c9b8a7",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
