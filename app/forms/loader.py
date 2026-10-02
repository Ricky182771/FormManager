"""Discovery and structural validation of form packages under FORMS_DIR.

All filesystem access goes through app.forms.fsutil (Linux/POSIX dir_fd + O_NOFOLLOW), so a
name never resolves outside the directory it was found in and symlinks are rejected.
"""

from __future__ import annotations

import json
import tomllib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.forms import fsutil
from app.forms.diagnostics import Diagnostic, DiagnosticCode, safe_name
from app.forms.fsutil import EntryKind, FsRejected
from app.forms.package import (
    DEFINITION_FILES,
    FORM_FILE,
    OPTIONAL_DIRS,
    RULES_FILE,
    SCHEMA_VERSION,
    FormDocument,
    FormPackage,
    is_valid_form_id,
)

MAX_DIAGNOSTICS_PER_FILE = 20

_FORM_FIELD_CODES = {
    "schema_version": DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION,
    "id": DiagnosticCode.INVALID_FORM_ID,
    "slug": DiagnosticCode.INVALID_SLUG,
    "status": DiagnosticCode.INVALID_STATUS,
}

_MSG_SYMLINK = "Los enlaces simbólicos no están permitidos dentro del paquete."
_MSG_SYMLINK_DIR = "El directorio del formulario no puede ser un enlace simbólico."

# fsutil rejection kind -> (code, message) for a definition file.
_FILE_REJECTIONS = {
    fsutil.MISSING: (DiagnosticCode.MISSING_FILE, "Falta el archivo obligatorio."),
    fsutil.SYMLINK: (DiagnosticCode.SYMLINK_NOT_ALLOWED, _MSG_SYMLINK),
    fsutil.NOT_REGULAR: (DiagnosticCode.NOT_A_REGULAR_FILE, "Debe ser un archivo regular."),
    fsutil.UNREADABLE: (DiagnosticCode.UNREADABLE_FILE, "No se puede leer."),
}


@dataclass(frozen=True, slots=True)
class PackageResult:
    package: FormPackage | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class ScanResult:
    forms: tuple[FormPackage, ...]
    diagnostics: tuple[Diagnostic, ...]
    # Directories that looked like packages, valid or not; used to count invalid packages.
    packages_seen: int


class _Rejected(Exception):
    def __init__(self, code: DiagnosticCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def scan_forms_dir(forms_dir: Path, max_bytes: int) -> ScanResult:
    """Load every direct child of FORMS_DIR. Errors in one package never affect another."""
    candidates: list[FormPackage] = []
    diagnostics: list[Diagnostic] = []
    seen = 0
    with fsutil.open_root(forms_dir) as root_fd:
        for name, kind in fsutil.list_entries(root_fd):
            # .tmp-* staging directories and any other dot entry are never packages.
            if name.startswith("."):
                continue
            if kind is EntryKind.SYMLINK:
                seen += 1
                diagnostics.append(
                    Diagnostic(
                        safe_name(name), None, DiagnosticCode.SYMLINK_NOT_ALLOWED, _MSG_SYMLINK_DIR
                    )
                )
                continue
            if kind is not EntryKind.DIRECTORY:
                continue
            seen += 1
            result = load_package(root_fd, name, forms_dir=forms_dir, max_bytes=max_bytes)
            diagnostics.extend(result.diagnostics)
            if result.package is not None:
                candidates.append(result.package)

    forms, conflicts = resolve_conflicts(candidates)
    return ScanResult(forms, (*diagnostics, *conflicts), seen)


def resolve_conflicts(
    candidates: Iterable[FormPackage],
) -> tuple[tuple[FormPackage, ...], tuple[Diagnostic, ...]]:
    """Reject every participant of an ID or slug collision; there is no "first wins"."""
    packages = list(candidates)
    by_id: dict[str, list[int]] = defaultdict(list)
    by_slug: dict[str, list[int]] = defaultdict(list)
    for index, package in enumerate(packages):
        by_id[package.id].append(index)
        by_slug[package.slug].append(index)

    rejected: set[int] = set()
    diagnostics: list[Diagnostic] = []
    for groups, code, label in (
        (by_id, DiagnosticCode.DUPLICATE_FORM_ID, "ID"),
        (by_slug, DiagnosticCode.DUPLICATE_SLUG, "slug"),
    ):
        for key, indexes in groups.items():
            if len(indexes) < 2:
                continue
            for index in indexes:
                others = sorted(packages[i].relative_path for i in indexes if i != index)
                diagnostics.append(
                    Diagnostic(
                        packages[index].relative_path,
                        FORM_FILE,
                        code,
                        f"El {label} {key!r} también lo declara: {', '.join(others)}.",
                    )
                )
                rejected.add(index)

    diagnostics.sort(key=lambda d: (d.relative_path, d.code))
    valid = sorted(
        (p for i, p in enumerate(packages) if i not in rejected), key=lambda p: (p.slug, p.id)
    )
    return tuple(valid), tuple(diagnostics)


def load_package(parent_fd: int, name: str, *, forms_dir: Path, max_bytes: int) -> PackageResult:
    """Validate the package directory `name` under `parent_fd`. The directory name must be the
    form ID; the atomic creator relies on this same check for its staged package."""
    rel = safe_name(name)
    if not is_valid_form_id(name):
        return PackageResult(
            None,
            (
                Diagnostic(
                    rel,
                    None,
                    DiagnosticCode.INVALID_DIRECTORY_NAME,
                    "El nombre del directorio no es un ID de formulario válido "
                    "(16 caracteres A-Z, a-z, 0-9, _ o -).",
                ),
            ),
        )

    diagnostics: list[Diagnostic] = []
    document: FormDocument | None = None
    try:
        with fsutil.open_subdir(parent_fd, name) as pkg_fd:
            diagnostics.extend(_check_optional_dirs(pkg_fd, rel))
            for file in DEFINITION_FILES:
                try:
                    raw = _read_definition(pkg_fd, file, max_bytes)
                    parsed = _parse_json(raw) if file == RULES_FILE else _parse_toml(raw)
                except _Rejected as rejected:
                    diagnostics.append(Diagnostic(rel, file, rejected.code, rejected.message))
                    continue
                if file == FORM_FILE:
                    document, problems = _validate_form(parsed)
                else:
                    problems = _check_schema_version(parsed)
                diagnostics.extend(Diagnostic(rel, file, code, msg) for code, msg in problems)
    except FsRejected as exc:
        code, message = {
            fsutil.SYMLINK: (DiagnosticCode.SYMLINK_NOT_ALLOWED, _MSG_SYMLINK_DIR),
            fsutil.NOT_DIRECTORY: (DiagnosticCode.NOT_A_DIRECTORY, "No es un directorio."),
        }.get(exc.kind, (DiagnosticCode.UNREADABLE_FILE, "No se puede abrir el directorio."))
        return PackageResult(None, (Diagnostic(rel, None, code, message),))

    if document is not None and document.id != name:
        diagnostics.append(
            Diagnostic(
                rel,
                FORM_FILE,
                DiagnosticCode.FORM_ID_MISMATCH,
                "El id de form.toml no coincide con el nombre del directorio.",
            )
        )
    if diagnostics or document is None:
        return PackageResult(None, tuple(diagnostics))
    return PackageResult(FormPackage.from_document(document, forms_dir), ())


def _check_optional_dirs(pkg_fd: int, rel: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for name in OPTIONAL_DIRS:
        try:
            kind = fsutil.entry_kind(pkg_fd, name)
        except FsRejected:
            diagnostics.append(
                Diagnostic(rel, name, DiagnosticCode.UNREADABLE_FILE, "No se puede inspeccionar.")
            )
            continue
        if kind is EntryKind.SYMLINK:
            diagnostics.append(
                Diagnostic(rel, name, DiagnosticCode.SYMLINK_NOT_ALLOWED, _MSG_SYMLINK)
            )
        elif kind not in (EntryKind.MISSING, EntryKind.DIRECTORY):
            diagnostics.append(
                Diagnostic(rel, name, DiagnosticCode.NOT_A_DIRECTORY, "Debe ser un directorio.")
            )
    return diagnostics


def _read_definition(pkg_fd: int, name: str, max_bytes: int) -> bytes:
    try:
        return fsutil.read_regular_file(pkg_fd, name, max_bytes)
    except FsRejected as exc:
        if exc.kind == fsutil.TOO_LARGE:
            raise _Rejected(
                DiagnosticCode.FILE_TOO_LARGE, f"Supera el límite de {max_bytes} bytes."
            ) from None
        code, message = _FILE_REJECTIONS.get(exc.kind, _FILE_REJECTIONS[fsutil.UNREADABLE])
        raise _Rejected(code, message) from None


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Rejected(DiagnosticCode.INVALID_ENCODING, "El archivo no es UTF-8 válido.") from None


def _parse_toml(raw: bytes) -> dict[str, Any]:
    text = _decode(raw)
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # tomllib messages carry the error kind and line/column, never source text.
        raise _Rejected(DiagnosticCode.INVALID_TOML, f"TOML inválido: {str(exc)[:200]}") from None
    except RecursionError:
        raise _Rejected(DiagnosticCode.INVALID_TOML, "TOML inválido: anidación excesiva.") from None


def _reject_constant(_: str) -> Any:
    raise ValueError("NaN and Infinity are not JSON")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _parse_json(raw: bytes) -> dict[str, Any]:
    text = _decode(raw)
    try:
        value = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_keys)
    except json.JSONDecodeError as exc:
        raise _Rejected(
            DiagnosticCode.INVALID_JSON,
            f"JSON inválido: {exc.msg} (línea {exc.lineno}, columna {exc.colno}).",
        ) from None
    except ValueError:
        raise _Rejected(
            DiagnosticCode.INVALID_JSON, "JSON inválido: claves duplicadas o NaN/Infinity."
        ) from None
    except RecursionError:
        raise _Rejected(DiagnosticCode.INVALID_JSON, "JSON inválido: anidación excesiva.") from None
    if not isinstance(value, dict):
        raise _Rejected(DiagnosticCode.INVALID_JSON_ROOT, "La raíz debe ser un objeto JSON.")
    return value


def _check_schema_version(document: dict[str, Any]) -> list[tuple[DiagnosticCode, str]]:
    if "schema_version" not in document:
        return [(DiagnosticCode.MISSING_PROPERTY, "Falta la propiedad obligatoria schema_version.")]
    value = document["schema_version"]
    if type(value) is not int or value != SCHEMA_VERSION:
        return [
            (
                DiagnosticCode.UNSUPPORTED_SCHEMA_VERSION,
                f"schema_version no soportada (se admite {SCHEMA_VERSION}).",
            )
        ]
    return []


def _validate_form(
    document: dict[str, Any],
) -> tuple[FormDocument | None, list[tuple[DiagnosticCode, str]]]:
    try:
        return FormDocument.model_validate(document), []
    except ValidationError as exc:
        problems: list[tuple[DiagnosticCode, str]] = []
        for error in exc.errors(include_input=False, include_url=False)[:MAX_DIAGNOSTICS_PER_FILE]:
            field = str(error["loc"][0]) if error["loc"] else ""
            if error["type"] == "extra_forbidden":
                problems.append(
                    (
                        DiagnosticCode.UNKNOWN_FORM_PROPERTY,
                        f"Propiedad desconocida {safe_name(field)}.",
                    )
                )
            elif error["type"] == "missing":
                problems.append(
                    (DiagnosticCode.MISSING_PROPERTY, f"Falta la propiedad obligatoria {field}.")
                )
            else:
                code = _FORM_FIELD_CODES.get(field, DiagnosticCode.INVALID_PROPERTY)
                problems.append((code, f"Valor inválido para {field}."))
        return None, problems
