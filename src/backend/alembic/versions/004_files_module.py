"""Grant File Manager permission on built-in roles when the key is absent.

Revision ID: 004_files_module
Revises: 003_rbac_access
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_files_module"
down_revision: Union[str, None] = "003_rbac_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE roles
            SET permissions = permissions || '{"files": "full"}'::jsonb
            WHERE slug IN ('superadmin', 'operator')
              AND NOT (permissions ? 'files')
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE roles
            SET permissions = permissions || '{"files": "read"}'::jsonb
            WHERE slug = 'viewer'
              AND NOT (permissions ? 'files')
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET permissions = permissions - 'files' WHERE is_system = true"))
