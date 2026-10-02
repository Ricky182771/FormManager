"""Synthetic form packages for tests. No real data."""

from __future__ import annotations

import json
from pathlib import Path

FORM_A = "AAAAAAAAAAAAAAAA"
FORM_B = "BBBBBBBBBBBBBBBB"
FORM_C = "CCCCCCCCCCCCCCCC"


def form_toml(form_id: str, slug: str, title: str = "Reserva de sala", **extra: str) -> str:
    lines = [
        "schema_version = 1",
        f'id = "{form_id}"',
        f'slug = "{slug}"',
        f"title = {json.dumps(title, ensure_ascii=False)}",
        'status = "draft"',
    ]
    lines += [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in extra.items()]
    return "\n".join(lines) + "\n"


def write_package(
    root: Path,
    form_id: str,
    slug: str,
    *,
    title: str = "Reserva de sala",
    form: str | None = None,
    skip: tuple[str, ...] = (),
) -> Path:
    package = root / form_id
    package.mkdir()
    files = {
        "form.toml": form if form is not None else form_toml(form_id, slug, title),
        "elements.toml": "schema_version = 1\n",
        "resources.toml": "schema_version = 1\n",
        "rules.json": json.dumps({"schema_version": 1, "rules": []}),
    }
    for name, content in files.items():
        if name not in skip:
            (package / name).write_text(content, encoding="utf-8")
    return package
