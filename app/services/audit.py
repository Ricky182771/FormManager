from __future__ import annotations

import logging
from enum import StrEnum

from sqlalchemy.orm import Session

from app.models import AdminAuditLog

logger = logging.getLogger("app.audit")


class AuditAction(StrEnum):
    ADMIN_LOGIN = "ADMIN_LOGIN"
    ADMIN_LOGIN_FAILED = "ADMIN_LOGIN_FAILED"
    ADMIN_LOGOUT = "ADMIN_LOGOUT"


def record_audit(db: Session, action: AuditAction, admin: str | None = None) -> None:
    """Add an audit row to the caller's transaction (caller commits).

    Failed logins record no username: a mistyped password often lands in that field.
    """
    details = {"admin": admin} if admin is not None else {}
    db.add(AdminAuditLog(action=action.value, details=details))
    logger.info("admin_action", extra={"action": action.value, **details})
