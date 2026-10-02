"""forms_registry: minimal index of form packages loaded from FORMS_DIR.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forms_registry",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("relative_path", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_forms_registry"),
        sa.UniqueConstraint(
            "slug", name="uq_forms_registry_slug", deferrable=True, initially="IMMEDIATE"
        ),
        sa.CheckConstraint("id ~ '^[A-Za-z0-9_-]{16}$'", name=op.f("ck_forms_registry_id_format")),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 80",
            name=op.f("ck_forms_registry_slug_format"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'paused', 'closed', 'archived')",
            name=op.f("ck_forms_registry_status_valid"),
        ),
        sa.CheckConstraint(
            "relative_path <> '' AND left(relative_path, 1) <> '/' "
            "AND position('..' in relative_path) = 0",
            name=op.f("ck_forms_registry_relative_path_relative"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name=op.f("ck_forms_registry_schema_version_positive")
        ),
    )


def downgrade() -> None:
    op.drop_table("forms_registry")
