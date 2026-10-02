"""Filesystem -> forms_registry sync. One transaction; deterministic; a no-op when unchanged.

Removal policy (Hito 1 only): a form that is gone or invalid is deleted from the registry,
because nothing references it yet. This must be revisited once submissions exist.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.forms.package import FormPackage
from app.models.form_registry import FormRegistryEntry

logger = logging.getLogger("app.forms")

_TRACKED = ("slug", "relative_path", "schema_version", "title", "status")


@dataclass(frozen=True, slots=True)
class RegistrySyncResult:
    inserted: int
    updated: int
    deleted: int


def sync_registry(
    session_factory: sessionmaker[Session], forms: Iterable[FormPackage]
) -> RegistrySyncResult:
    """Make forms_registry equal to `forms`. Any database error propagates after rollback."""
    wanted = {form.id: form for form in forms}
    with session_factory() as session, session.begin():
        # Concurrent syncs (another process) wait here instead of interleaving.
        session.execute(text("LOCK TABLE forms_registry IN SHARE ROW EXCLUSIVE MODE"))
        session.execute(text("SET CONSTRAINTS uq_forms_registry_slug DEFERRED"))
        existing = {
            row.id: row
            for row in session.scalars(select(FormRegistryEntry).order_by(FormRegistryEntry.id))
        }

        stale = sorted(set(existing) - set(wanted))
        if stale:
            session.execute(delete(FormRegistryEntry).where(FormRegistryEntry.id.in_(stale)))

        inserted = updated = 0
        for form_id in sorted(wanted):
            form = wanted[form_id]
            values = {
                "slug": form.slug,
                "relative_path": form.relative_path,
                "schema_version": form.schema_version,
                "title": form.title,
                "status": form.status,
            }
            row = existing.get(form_id)
            if row is None:
                # updated_at comes from the column's server_default now().
                session.add(FormRegistryEntry(id=form_id, **values))
                inserted += 1
            elif any(getattr(row, key) != values[key] for key in _TRACKED):
                # PostgreSQL is the clock for updated_at, on insert and on update alike.
                session.execute(
                    update(FormRegistryEntry)
                    .where(FormRegistryEntry.id == form_id)
                    .values(**values, updated_at=func.now())
                    .execution_options(synchronize_session=False)
                )
                updated += 1
        session.flush()

    result = RegistrySyncResult(inserted, updated, len(stale))
    logger.info(
        "form_registry_synced",
        extra={
            "registry_inserted": result.inserted,
            "registry_updated": result.updated,
            "registry_deleted": result.deleted,
        },
    )
    return result
