"""FORMS_DIR preparation. Hito 0 only guarantees the directory is usable; it never reads it."""

from __future__ import annotations

import os
from pathlib import Path


class StorageError(RuntimeError):
    pass


def prepare_forms_dir(path: Path) -> Path:
    """Create FORMS_DIR if missing and check it is a writable directory. Contents are not read."""
    if path.is_symlink():
        raise StorageError("FORMS_DIR must not be a symlink")
    if not path.exists():
        try:
            path.mkdir(mode=0o750, parents=True)
        except OSError as exc:
            raise StorageError("FORMS_DIR does not exist and cannot be created") from exc
    if not path.is_dir():
        raise StorageError("FORMS_DIR is not a directory")
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        raise StorageError("FORMS_DIR is not readable and writable by the application user")
    return path.resolve()


# There is no Form Loader yet (Hito 1), so nothing in FORMS_DIR is ever loaded.
FORMS_LOADED = 0
