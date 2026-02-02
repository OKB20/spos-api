from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...db import get_db
from ...models import AuditLog, User
from ...schemas import AuditLogBase

from uuid import UUID

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("/", response_model=List[AuditLogBase])
def list_audit_logs(
    limit: int = 200,
    table_name: str | None = None,
    user_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("audit.read",))),
):
    limit = max(1, min(limit, 500))
    query = db.query(AuditLog)
    if table_name:
        query = query.filter(AuditLog.table_name == table_name)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()
