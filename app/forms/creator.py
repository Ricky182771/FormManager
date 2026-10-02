"""Internal, atomic creation of a minimal form package. Not exposed over HTTP in Hito 1.

Layout while staging:  FORMS_DIR/.tmp-<random>/<form-id>/{form.toml,...}
The staged <form-id>/ is validated by the normal loader (no relaxed mode), then renamed to
FORMS_DIR/<form-id> on the same filesystem, and the empty staging directory is removed.
The catalog only sees the new package after an explicit reload.
"""

from __future__ import annotations

import json
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from app.forms import fsutil
from app.forms.fsutil import EntryKind
from app.forms.loader import load_package, scan_forms_dir
from app.forms.package import (
    ELEMENTS_FILE,
    FORM_FILE,
    RESOURCES_FILE,
    RULES_FILE,
    SCHEMA_VERSION,
    FormDocument,
    FormPackage,
    FormStatus,
    new_form_id,
)

TMP_PREFIX = ".tmp-"


class FormCreationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _toml_string(value: str) -> str:
    # A JSON string literal is a valid TOML basic string for the characters FormDocument allows.
    return json.dumps(value, ensure_ascii=False)


def _render_form_toml(doc: FormDocument) -> str:
    lines = [
        f"schema_version = {doc.schema_version}",
        f"id = {_toml_string(doc.id)}",
        f"slug = {_toml_string(doc.slug)}",
        f"title = {_toml_string(doc.title)}",
    ]
    if doc.subtitle is not None:
        lines.append(f"subtitle = {_toml_string(doc.subtitle)}")
    if doc.description is not None:
        lines.append(f"description = {_toml_string(doc.description)}")
    lines.append(f"status = {_toml_string(doc.status)}")
    return "\n".join(lines) + "\n"


def _skeleton(doc: FormDocument) -> dict[str, str]:
    return {
        FORM_FILE: _render_form_toml(doc),
        ELEMENTS_FILE: f"schema_version = {SCHEMA_VERSION}\n",
        RESOURCES_FILE: f"schema_version = {SCHEMA_VERSION}\n",
        RULES_FILE: json.dumps({"schema_version": SCHEMA_VERSION, "rules": []}, indent=2) + "\n",
    }


def create_form_package(
    forms_dir: Path,
    *,
    slug: str,
    title: str,
    max_bytes: int,
    subtitle: str | None = None,
    description: str | None = None,
    status: FormStatus = "draft",
    id_factory: Callable[[], str] = new_form_id,
) -> FormPackage:
    form_id = id_factory()
    try:
        doc = FormDocument.model_validate(
            {
                "schema_version": SCHEMA_VERSION,
                "id": form_id,
                "slug": slug,
                "title": title,
                "subtitle": subtitle,
                "description": description,
                "status": status,
            }
        )
    except ValidationError as exc:
        fields = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        raise FormCreationError("INVALID_INPUT", f"Datos inválidos: {', '.join(fields)}.") from None

    # A second package with the same slug would make both invalid on the next reload.
    # Not race-free against a concurrent creator: callers must serialise creation.
    if any(form.slug == slug for form in scan_forms_dir(forms_dir, max_bytes).forms):
        raise FormCreationError("SLUG_TAKEN", "Ya existe un formulario con ese slug.")

    staging = f"{TMP_PREFIX}{secrets.token_hex(8)}"
    with fsutil.open_root(forms_dir) as root_fd:
        if fsutil.entry_kind(root_fd, form_id) is not EntryKind.MISSING:
            raise FormCreationError("FORM_EXISTS", "Ya existe un paquete con ese ID.")
        fsutil.make_dir(root_fd, staging)
        try:
            with fsutil.open_subdir(root_fd, staging) as staging_fd:
                fsutil.make_dir(staging_fd, form_id)
                with fsutil.open_subdir(staging_fd, form_id) as pkg_fd:
                    for name, content in _skeleton(doc).items():
                        fsutil.write_new_file(pkg_fd, name, content.encode("utf-8"))
                    fsutil.fsync_dir(pkg_fd)

                result = load_package(staging_fd, form_id, forms_dir=forms_dir, max_bytes=max_bytes)
                package = result.package
                if package is None:
                    codes = ", ".join(sorted({d.code.value for d in result.diagnostics}))
                    raise FormCreationError(
                        "INVALID_PACKAGE", f"El paquete generado es inválido: {codes}."
                    )
                if fsutil.entry_kind(root_fd, form_id) is not EntryKind.MISSING:
                    raise FormCreationError("FORM_EXISTS", "Ya existe un paquete con ese ID.")
                fsutil.move_dir(staging_fd, form_id, root_fd, form_id)
                fsutil.fsync_dir(root_fd)
            fsutil.remove_empty_dir(root_fd, staging)
        except BaseException:
            # The staging name is ours and never a package (dot prefix), so removing it is safe.
            shutil.rmtree(forms_dir / staging, ignore_errors=True)
            raise
    return package
