from typing import Callable, Iterable, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from ..core.permissions import get_default_permissions
from ..core.security import decode_token
from ..db import get_db
from ..models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == UUID(user_id)).first()
    if user is None:
        raise credentials_exception
    return user


def _match_permission(granted: str, required: str) -> bool:
    if granted == "*":
        return True
    if granted.endswith("*"):
        return required.startswith(granted[:-1])
    return granted == required


def _extract_permission_lists(perms: object) -> tuple[set[str], set[str]]:
    if not isinstance(perms, dict):
        return set(), set()
    allow = perms.get("allow")
    deny = perms.get("deny")
    allow_list = set(allow) if isinstance(allow, list) else set()
    deny_list = set(deny) if isinstance(deny, list) else set()
    return allow_list, deny_list


def has_permission(user: User, required: str) -> bool:
    if user.role == "admin":
        return True
    default_allow = get_default_permissions(user.role)
    explicit_allow, explicit_deny = _extract_permission_lists(user.permissions)
    allow = default_allow.union(explicit_allow)
    if explicit_deny and any(_match_permission(d, required) for d in explicit_deny):
        return False
    if allow and any(_match_permission(a, required) for a in allow):
        return True
    return False


def require_role(*roles: str, allow_perms: Optional[Iterable[str]] = None) -> Callable[[User], User]:
    def _role_guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == "admin":
            return current_user
        if allow_perms:
            if any(has_permission(current_user, perm) for perm in allow_perms):
                return current_user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        if roles and (current_user.role in roles):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    return _role_guard
