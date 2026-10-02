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
    elements: str = "schema_version = 1\n",
    skip: tuple[str, ...] = (),
) -> Path:
    package = root / form_id
    package.mkdir()
    files = {
        "form.toml": form if form is not None else form_toml(form_id, slug, title),
        "elements.toml": elements,
        "resources.toml": "schema_version = 1\n",
        "rules.json": json.dumps({"schema_version": 1, "rules": []}),
    }
    for name, content in files.items():
        if name not in skip:
            (package / name).write_text(content, encoding="utf-8")
    return package


def element_toml(
    element_id: str = "field",
    element_type: str = "text",
    *,
    required: bool = True,
    extra: str = "",
    label: str = "Campo",
) -> str:
    """One [[element]] table. `extra` goes last, so it may open sub-tables like normalize."""
    return (
        f'[[element]]\nid = "{element_id}"\ntype = "{element_type}"\n'
        f"label = {json.dumps(label, ensure_ascii=False)}\nrequired = {str(required).lower()}\n"
        f"{extra}"
    )


def elements_toml(*elements: str) -> str:
    return "schema_version = 1\n" + "\n".join(elements)
