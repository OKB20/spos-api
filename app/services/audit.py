from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import AuditLog


def record_audit(
    db: Session,
    user_id: UUID,
    action: str,
    table_name: str,
    record_id: Optional[UUID] = None,
    old_values: Optional[dict[str, Any]] = None,
    new_values: Optional[dict[str, Any]] = None,
) -> None:
    log = AuditLog(
        user_id=user_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values,
    )
    db.add(log)
