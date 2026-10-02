"""Runtime catalog of valid form packages, replaced as a whole snapshot on reload."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from app.forms.diagnostics import Diagnostic
from app.forms.loader import scan_forms_dir
from app.forms.package import FormPackage

logger = logging.getLogger("app.forms")

RegistrySync = Callable[[tuple[FormPackage, ...]], object]


@dataclass(frozen=True)
class CatalogSnapshot:
    forms: tuple[FormPackage, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    invalid_packages: int = 0
    by_id: Mapping[str, FormPackage] = field(default_factory=lambda: MappingProxyType({}))
    by_slug: Mapping[str, FormPackage] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def build(
        cls, forms: tuple[FormPackage, ...], diagnostics: tuple[Diagnostic, ...], invalid: int
    ) -> CatalogSnapshot:
        return cls(
            forms=forms,
            diagnostics=diagnostics,
            invalid_packages=invalid,
            by_id=MappingProxyType({f.id: f for f in forms}),
            by_slug=MappingProxyType({f.slug: f for f in forms}),
        )


class FormCatalog:
    """Readers always see one complete snapshot; reload builds and syncs a new one, then swaps."""

    def __init__(self, forms_dir: Path, max_bytes: int, registry_sync: RegistrySync) -> None:
        self._forms_dir = forms_dir
        self._max_bytes = max_bytes
        self._registry_sync = registry_sync
        self._snapshot = CatalogSnapshot()
        # Serialises reloads so an older scan can never be synced or swapped after a newer one.
        self._reload_lock = threading.Lock()

    @property
    def snapshot(self) -> CatalogSnapshot:
        return self._snapshot

    def forms(self) -> tuple[FormPackage, ...]:
        """Valid forms ordered by slug."""
        return self._snapshot.forms

    def get_by_id(self, form_id: str) -> FormPackage | None:
        return self._snapshot.by_id.get(form_id)

    def get_by_slug(self, slug: str) -> FormPackage | None:
        return self._snapshot.by_slug.get(slug)

    @property
    def count(self) -> int:
        return len(self._snapshot.forms)

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self._snapshot.diagnostics

    def reload(self) -> CatalogSnapshot:
        """Scan FORMS_DIR, sync forms_registry, then publish. A sync failure propagates and the
        previous snapshot stays in place: filesystem and registry never diverge silently."""
        with self._reload_lock:
            logger.info("form_load_started")
            scan = scan_forms_dir(self._forms_dir, self._max_bytes)
            for diagnostic in scan.diagnostics:
                logger.warning(
                    "form_load_failed",
                    extra={
                        "relative_path": diagnostic.relative_path,
                        "file": diagnostic.file,
                        "error_code": diagnostic.code.value,
                        "detail": diagnostic.message,
                    },
                )
            for form in scan.forms:
                logger.info(
                    "form_loaded",
                    extra={
                        "form_id": form.id,
                        "slug": form.slug,
                        "relative_path": form.relative_path,
                    },
                )
            try:
                self._registry_sync(scan.forms)
            except Exception as exc:
                logger.error("form_registry_sync_failed", extra={"error_type": type(exc).__name__})
                raise
            snapshot = CatalogSnapshot.build(
                scan.forms, scan.diagnostics, scan.packages_seen - len(scan.forms)
            )
            self._snapshot = snapshot
            logger.info(
                "form_catalog_loaded",
                extra={
                    "forms_valid": len(snapshot.forms),
                    "forms_invalid": snapshot.invalid_packages,
                },
            )
            return snapshot
