"""Load diagnostics: why a package was rejected, safe to log (no absolute paths, no content)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class DiagnosticCode(StrEnum):
    INVALID_DIRECTORY_NAME = "INVALID_DIRECTORY_NAME"
    SYMLINK_NOT_ALLOWED = "SYMLINK_NOT_ALLOWED"
    MISSING_FILE = "MISSING_FILE"
    NOT_A_REGULAR_FILE = "NOT_A_REGULAR_FILE"
    NOT_A_DIRECTORY = "NOT_A_DIRECTORY"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNREADABLE_FILE = "UNREADABLE_FILE"
    INVALID_ENCODING = "INVALID_ENCODING"
    INVALID_TOML = "INVALID_TOML"
    INVALID_JSON = "INVALID_JSON"
    INVALID_JSON_ROOT = "INVALID_JSON_ROOT"
    UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"
    MISSING_PROPERTY = "MISSING_PROPERTY"
    UNKNOWN_FORM_PROPERTY = "UNKNOWN_FORM_PROPERTY"
    INVALID_PROPERTY = "INVALID_PROPERTY"
    INVALID_FORM_ID = "INVALID_FORM_ID"
    INVALID_SLUG = "INVALID_SLUG"
    INVALID_STATUS = "INVALID_STATUS"
    FORM_ID_MISMATCH = "FORM_ID_MISMATCH"
    DUPLICATE_FORM_ID = "DUPLICATE_FORM_ID"
    DUPLICATE_SLUG = "DUPLICATE_SLUG"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    relative_path: str
    file: str | None
    code: DiagnosticCode
    message: str


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}\Z")


def safe_name(name: str) -> str:
    """Directory or key names come from the filesystem; escape anything unusual before logging."""
    if _SAFE_NAME_RE.match(name):
        return name
    return ascii(name[:80])
