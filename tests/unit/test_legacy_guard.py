"""Does the Core hardcode the prototype's business logic?

Checks concrete legacy symbols, files, tables and settings only. Ordinary form vocabulary
("team", "student", "topic"...) is deliberately allowed: user-defined forms may use it.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import models  # noqa: F401  (registers tables on the metadata)
from app.config import Settings
from app.db.base import Base

ROOT = Path(__file__).resolve().parents[2]

LEGACY_CORE_SYMBOLS = (
    "MAX_TEAMS",
    "TEAM_SIZE",
    "TOTAL_STUDENTS",
    "TeamMember",
    "MemberRole",
    "TeamView",
    "RegistrationIn",
    "register_team",
    "seed_data",
    "TEAM_DELETED",
    "REGISTRATION_OPENED",
    "REGISTRATION_CLOSED",
    "REGISTRATION_OPEN_ON_SEED",
    "REGISTRATION_ACCESS_CODE_HASH",
)
LEGACY_FILES = (
    "app/seed.py",
    "app/seed_data.py",
    "app/models/student.py",
    "app/models/topic.py",
    "app/models/team.py",
    "app/models/team_member.py",
    "app/models/settings.py",
    "app/schemas/registration.py",
    "app/services/registration.py",
)
LEGACY_TABLES = {"students", "topics", "teams", "team_members", "app_settings"}
LEGACY_SETTINGS = {
    "registration_access_enabled",
    "registration_access_code_hash",
    "registration_rate_limit",
    "access_code_rate_limit",
    "registration_open_on_seed",
}

# Core code and deployment config; docs and tests may describe the prototype.
SCANNED = ("app", "alembic", "docker", "scripts")
SCANNED_FILES = (".env.example", "docker-compose.yml", "docker-compose.test.yml", "Dockerfile")
SUFFIXES = {".py", ".html", ".css", ".js", ".sh", ".mako", ".sql", ".toml", ".yml"}
SYMBOL_RE = re.compile(r"\b(?:" + "|".join(map(re.escape, LEGACY_CORE_SYMBOLS)) + r")\b")


def _core_files() -> list[Path]:
    files = [ROOT / name for name in SCANNED_FILES]
    for folder in SCANNED:
        files += [p for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in SUFFIXES]
    return files


def test_core_has_no_legacy_domain_symbols() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno}: {match.group(0)}"
        for path in _core_files()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for match in SYMBOL_RE.finditer(line)
    ]
    assert offenders == []


def test_guard_detects_a_legacy_symbol() -> None:
    assert SYMBOL_RE.search("MAX_TEAMS = 11")
    assert SYMBOL_RE.search("from app.seed_data import ROSTER")
    assert not SYMBOL_RE.search('label = "Team registration"  # a user-defined form')


def test_core_has_no_legacy_modules() -> None:
    assert [f for f in LEGACY_FILES if (ROOT / f).exists()] == []


def test_core_schema_has_no_legacy_tables() -> None:
    assert set(Base.metadata.tables) & LEGACY_TABLES == set()


def test_settings_have_no_legacy_fields() -> None:
    assert set(Settings.model_fields) & LEGACY_SETTINGS == set()
