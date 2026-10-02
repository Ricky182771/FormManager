"""Catalog snapshot swaps and registry syncs under concurrency (real PostgreSQL)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.forms.catalog import FormCatalog
from app.forms.loader import scan_forms_dir
from app.forms.package import FormPackage
from app.forms.registry import sync_registry
from tests.forms_fixtures import FORM_A, FORM_B, FORM_C, form_toml, write_package

MAX = 64 * 1024


def test_readers_never_see_a_partial_catalog(tmp_path: Path) -> None:
    write_package(tmp_path, FORM_A, "a")
    write_package(tmp_path, FORM_B, "b")
    write_package(tmp_path, FORM_C, "c")
    catalog = FormCatalog(tmp_path, MAX, lambda forms: None)
    catalog.reload()
    stop = threading.Event()
    bad: list[int] = []

    def reader() -> None:
        while not stop.is_set():
            snap = catalog.snapshot
            if len(snap.forms) != 3 or len(snap.by_slug) != 3 or len(snap.by_id) != 3:
                bad.append(len(snap.forms))
            time.sleep(0)  # yield the GIL so reloads make progress

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for _ in range(20):
        catalog.reload()
    stop.set()
    for t in threads:
        t.join()
    assert bad == []


def test_concurrent_syncs_serialise_and_converge(
    engine: Engine, session_factory: sessionmaker[Session], forms_root: Path
) -> None:
    a = write_package(forms_root, FORM_A, "first")
    b = write_package(forms_root, FORM_B, "second")
    before = scan_forms_dir(forms_root, MAX).forms
    (a / "form.toml").write_text(form_toml(FORM_A, "second"))
    (b / "form.toml").write_text(form_toml(FORM_B, "first"))
    after = scan_forms_dir(forms_root, MAX).forms
    barrier = threading.Barrier(8)

    def run(forms: tuple[FormPackage, ...]) -> None:
        barrier.wait()
        sync_registry(session_factory, forms)

    # Alternating slug swaps would violate uq_forms_registry_slug if syncs interleaved.
    batches = [before, after] * 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(run, batches))
    sync_registry(session_factory, after)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, slug FROM forms_registry ORDER BY id")).all()
    assert [tuple(r) for r in result] == [(FORM_A, "second"), (FORM_B, "first")]
