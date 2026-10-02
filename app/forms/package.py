"""The form package contract: identifiers, form.toml schema, FormPackage (elements.toml lives in
app.forms.elements)."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, field_validator

from app.forms.elements import ElementsSchema

SCHEMA_VERSION = 1

FORM_FILE = "form.toml"
ELEMENTS_FILE = "elements.toml"
RESOURCES_FILE = "resources.toml"
RULES_FILE = "rules.json"
DEFINITION_FILES = (FORM_FILE, ELEMENTS_FILE, RESOURCES_FILE, RULES_FILE)
OPTIONAL_DIRS = ("resources", "assets", "ui")

FORM_ID_LENGTH = 16
FORM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16}\Z")
SLUG_MAX_LENGTH = 80
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z")

TITLE_MAX_LENGTH = 200
SUBTITLE_MAX_LENGTH = 300
DESCRIPTION_MAX_LENGTH = 20_000

FormStatus = Literal["draft", "open", "paused", "closed", "archived"]
FORM_STATUSES: tuple[str, ...] = get_args(FormStatus)

# C0 controls and DEL. PostgreSQL rejects NUL in text, so these must never reach the registry.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CONTROL_EXCEPT_WHITESPACE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def is_valid_form_id(value: object) -> bool:
    return isinstance(value, str) and FORM_ID_RE.match(value) is not None


def is_valid_slug(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= SLUG_MAX_LENGTH
        and SLUG_RE.match(value) is not None
    )


def new_form_id() -> str:
    # token_urlsafe(12) is 16 chars of [A-Za-z0-9_-] carrying 96 random bits.
    return secrets.token_urlsafe(12)


class FormDocument(BaseModel):
    """form.toml, schema_version 1. Unknown keys are errors, never ignored."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: int
    id: str
    slug: str
    title: str
    subtitle: str | None = None
    description: str | None = None
    status: FormStatus

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version(cls, value: Any) -> Any:
        # type() rather than isinstance(): TOML `true` is a bool, and bool is an int subclass.
        if type(value) is not int or value != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        return value

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not is_valid_form_id(value):
            raise ValueError("invalid form id")
        return value

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not is_valid_slug(value):
            raise ValueError("invalid slug")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not value.strip() or len(value) > TITLE_MAX_LENGTH or _CONTROL_RE.search(value):
            raise ValueError("invalid title")
        return value

    @field_validator("subtitle")
    @classmethod
    def _subtitle(cls, value: str | None) -> str | None:
        if value is not None and (len(value) > SUBTITLE_MAX_LENGTH or _CONTROL_RE.search(value)):
            raise ValueError("invalid subtitle")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) > DESCRIPTION_MAX_LENGTH or _CONTROL_EXCEPT_WHITESPACE_RE.search(value)
        ):
            raise ValueError("invalid description")
        return value


@dataclass(frozen=True, slots=True)
class FormPackage:
    """A valid package: form.toml and elements.toml are interpreted; resources and rules are not
    interpreted yet."""

    id: str
    slug: str
    title: str
    subtitle: str | None
    description: str | None
    status: FormStatus
    schema_version: int
    # Relative to FORMS_DIR; the only path that may leave the process (logs, registry).
    relative_path: str
    package_path: Path
    elements: ElementsSchema

    @classmethod
    def from_document(
        cls, doc: FormDocument, forms_dir: Path, elements: ElementsSchema
    ) -> FormPackage:
        return cls(
            id=doc.id,
            slug=doc.slug,
            title=doc.title,
            subtitle=doc.subtitle,
            description=doc.description,
            status=doc.status,
            schema_version=doc.schema_version,
            relative_path=doc.id,
            package_path=forms_dir / doc.id,
            elements=elements,
        )
