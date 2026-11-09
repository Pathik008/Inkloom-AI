"""Phase 3: Add uq_brand_kit_single_published partial unique index on brand_kit_versions.

Revision ID: 0004_single_published_version
Revises: 0003_phase3_brand_hub
Create Date: 2026-11-08 18:38:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_single_published_version"
down_revision: Union[str, None] = "0003_phase3_brand_hub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_brand_kit_single_published",
        "brand_kit_versions",
        ["brand_kit_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
        sqlite_where=sa.text("status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_brand_kit_single_published",
        table_name="brand_kit_versions",
    )
