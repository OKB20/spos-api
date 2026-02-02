from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...core.permissions import get_default_permissions
from ...core.security import get_password_hash
from ...db import get_db
from ...models import User
from ...schemas import UserBase, UserPasswordReset, UserUpdate
from ...services.audit import record_audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserBase])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("users.read",))),
):
    return db.query(User).order_by(User.created_at.desc()).limit(200).all()


@router.patch("/{user_id}", response_model=UserBase)
def update_user(
    user_id: UUID,
    updates: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("users.write",))),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    data = updates.model_dump(exclude_unset=True)
    old_values = {}
    if "permissions" in data and data["permissions"] is not None:
        perms = data["permissions"] if isinstance(data["permissions"], dict) else {}
        allow = perms.get("allow") if isinstance(perms, dict) else None
        deny = perms.get("deny") if isinstance(perms, dict) else None
        data["permissions"] = {
            "allow": list(allow) if isinstance(allow, list) else [],
            "deny": list(deny) if isinstance(deny, list) else [],
        }
    if "role" in data and "permissions" not in data:
        default_allow = sorted(get_default_permissions(data.get("role")))
        data["permissions"] = {"allow": default_allow, "deny": []} if default_allow else None

    for field, value in data.items():
        old_values[field] = getattr(user, field)
        setattr(user, field, value)

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="profiles",
        record_id=user.id,
        old_values=old_values,
        new_values=data,
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserBase)
def reset_user_password(
    user_id: UUID,
    payload: UserPasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("users.write",))),
) -> UserBase:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = get_password_hash(payload.password)

    record_audit(
        db,
        user_id=current_user.id,
        action="RESET_PASSWORD",
        table_name="profiles",
        record_id=user.id,
    )

    db.commit()
    db.refresh(user)
    return user
