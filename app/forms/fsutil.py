"""Symlink-safe filesystem primitives for form packages.

Requires Linux/POSIX: openat-style dir_fd access, O_NOFOLLOW, O_DIRECTORY and renameat.
That is the supported runtime (the v1 Docker image). Every path is a single name resolved
against an open directory fd, so nothing can escape the directory it was found in.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
# O_NONBLOCK: a FIFO swapped in after the lstat check must not block the reader.
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_CHUNK = 64 * 1024


class EntryKind(Enum):
    MISSING = "missing"
    SYMLINK = "symlink"
    DIRECTORY = "directory"
    REGULAR = "regular"
    OTHER = "other"


class FsRejected(Exception):
    """A single entry is unusable. Carries a kind, never a path."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


SYMLINK = "symlink"
NOT_DIRECTORY = "not_directory"
NOT_REGULAR = "not_regular"
MISSING = "missing"
TOO_LARGE = "too_large"
UNREADABLE = "unreadable"


@contextmanager
def open_root(path: os.PathLike[str] | str) -> Iterator[int]:
    """Open FORMS_DIR itself; a symlinked root is refused (OSError propagates as infra error)."""
    fd = os.open(path, _DIR_FLAGS)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def open_subdir(parent_fd: int, name: str) -> Iterator[int]:
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise FsRejected(SYMLINK) from None
        if exc.errno == errno.ENOTDIR:
            raise FsRejected(NOT_DIRECTORY) from None
        if exc.errno == errno.ENOENT:
            raise FsRejected(MISSING) from None
        raise FsRejected(UNREADABLE) from None
    try:
        yield fd
    finally:
        os.close(fd)


def list_entries(dir_fd: int) -> list[tuple[str, EntryKind]]:
    """Direct children, sorted by name, classified without following symlinks."""
    with os.scandir(dir_fd) as it:
        return sorted((entry.name, _kind_of_entry(entry)) for entry in it)


def _kind_of_entry(entry: os.DirEntry[str]) -> EntryKind:
    if entry.is_symlink():
        return EntryKind.SYMLINK
    if entry.is_dir(follow_symlinks=False):
        return EntryKind.DIRECTORY
    if entry.is_file(follow_symlinks=False):
        return EntryKind.REGULAR
    return EntryKind.OTHER


def entry_kind(dir_fd: int, name: str) -> EntryKind:
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return EntryKind.MISSING
    except OSError:
        raise FsRejected(UNREADABLE) from None
    if stat.S_ISLNK(st.st_mode):
        return EntryKind.SYMLINK
    if stat.S_ISDIR(st.st_mode):
        return EntryKind.DIRECTORY
    if stat.S_ISREG(st.st_mode):
        return EntryKind.REGULAR
    return EntryKind.OTHER


def read_regular_file(dir_fd: int, name: str, max_bytes: int) -> bytes:
    """Read a regular, non-symlink file of at most max_bytes, checking size before reading."""
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise FsRejected(MISSING) from None
    except OSError:
        raise FsRejected(UNREADABLE) from None
    if stat.S_ISLNK(st.st_mode):
        raise FsRejected(SYMLINK)
    if not stat.S_ISREG(st.st_mode):
        raise FsRejected(NOT_REGULAR)
    if st.st_size > max_bytes:
        raise FsRejected(TOO_LARGE)

    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        raise FsRejected(SYMLINK if exc.errno == errno.ELOOP else UNREADABLE) from None
    try:
        opened = os.fstat(fd)
        # The entry may have been swapped between lstat and open.
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            st.st_dev,
            st.st_ino,
        ):
            raise FsRejected(NOT_REGULAR)
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(fd, min(_READ_CHUNK, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError:
        raise FsRejected(UNREADABLE) from None
    finally:
        os.close(fd)
    if total > max_bytes:
        raise FsRejected(TOO_LARGE)
    return b"".join(chunks)


def make_dir(parent_fd: int, name: str) -> None:
    os.mkdir(name, mode=0o750, dir_fd=parent_fd)


def write_new_file(dir_fd: int, name: str, content: bytes) -> None:
    """Create (never overwrite) and fsync a file."""
    fd = os.open(name, _CREATE_FLAGS, 0o640, dir_fd=dir_fd)
    try:
        data = memoryview(content)
        while data:
            data = data[os.write(fd, data) :]
        os.fsync(fd)
    finally:
        os.close(fd)


def move_dir(src_fd: int, src_name: str, dst_fd: int, dst_name: str) -> None:
    """Atomic same-filesystem rename. rename(2) never replaces a non-empty directory; callers
    must check the destination is absent first to also exclude empty directories."""
    os.rename(src_name, dst_name, src_dir_fd=src_fd, dst_dir_fd=dst_fd)


def remove_empty_dir(parent_fd: int, name: str) -> None:
    os.rmdir(name, dir_fd=parent_fd)


def fsync_dir(dir_fd: int) -> None:
    os.fsync(dir_fd)
