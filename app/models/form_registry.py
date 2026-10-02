from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FormRegistryEntry(Base):
    """Index of the forms currently loaded from FORMS_DIR. The filesystem stays canonical:
    no definition content is stored here."""

    __tablename__ = "forms_registry"
    __table_args__ = (
        # Deferrable so one sync can swap slugs between two forms; checked at commit.
        UniqueConstraint("slug", deferrable=True, initially="IMMEDIATE"),
        CheckConstraint("id ~ '^[A-Za-z0-9_-]{16}$'", name="id_format"),
        CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 80", name="slug_format"
        ),
        CheckConstraint(
            "status IN ('draft', 'open', 'paused', 'closed', 'archived')", name="status_valid"
        ),
        CheckConstraint(
            "relative_path <> '' AND left(relative_path, 1) <> '/' "
            "AND position('..' in relative_path) = 0",
            name="relative_path_relative",
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # When this row's metadata last changed (insert or update). An unchanged form is not
    # rewritten on reload, which keeps the sync a true no-op.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
