from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.storage import StorageError, prepare_forms_dir


def test_creates_missing_forms_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "forms"
    assert prepare_forms_dir(target) == target.resolve()
    assert target.is_dir()


def test_accepts_existing_forms_dir(tmp_path: Path) -> None:
    assert prepare_forms_dir(tmp_path) == tmp_path.resolve()


def test_rejects_file(tmp_path: Path) -> None:
    target = tmp_path / "forms"
    target.write_text("not a directory")
    with pytest.raises(StorageError, match="not a directory"):
        prepare_forms_dir(target)


def test_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "forms"
    link.symlink_to(real)
    with pytest.raises(StorageError, match="symlink"):
        prepare_forms_dir(link)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_rejects_read_only_dir(tmp_path: Path) -> None:
    target = tmp_path / "forms"
    target.mkdir(mode=0o500)
    try:
        with pytest.raises(StorageError, match="writable"):
            prepare_forms_dir(target)
    finally:
        target.chmod(0o700)


def test_prepare_does_not_read_contents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "form.toml").write_text("this must not be parsed")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("prepare_forms_dir must not scan; the Form Loader does")

    monkeypatch.setattr(os, "listdir", forbidden)
    monkeypatch.setattr(os, "scandir", forbidden)
    monkeypatch.setattr(Path, "iterdir", forbidden)
    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    prepare_forms_dir(tmp_path)
