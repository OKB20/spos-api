from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ...core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)
from ...core.permissions import get_default_permissions
from ...db import get_db
from ...models import User
from ...schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    Token,
    UserBase,
    UserCreate,
    UserSelfUpdate,
)
from ..deps import get_current_user
from ...core.config import get_settings
from ...services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserBase, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)) -> UserBase:
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    if len(user_in.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password too long",
        )

    default_allow = sorted(get_default_permissions(user_in.role))
    permissions = {"allow": default_allow, "deny": []} if default_allow else None

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        phone=user_in.phone,
        role=user_in.role,
        store_name=user_in.store_name,
        hashed_password=get_password_hash(user_in.password),
        permissions=permissions,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    if len(form_data.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password too long",
        )
    user = db.query(User).filter(User.email == form_data.username).first()
    try:
        valid_password = user and verify_password(form_data.password, user.hashed_password)
    except ValueError:
        valid_password = False
    if not user or not valid_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        # Placeholder: hook an email service or token generation here in the future.
        pass
    return {
        "detail": "Si un compte correspond à cet email, un lien de réinitialisation a été envoyé.",
    }


@router.get("/me", response_model=UserBase)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserBase:
    return current_user


@router.patch("/me", response_model=UserBase)
def update_current_user(
    updates: UserSelfUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserBase:
    data = updates.model_dump(exclude_unset=True)
    if not data:
        return current_user

    old_values = {}
    for field, value in data.items():
        old_values[field] = getattr(current_user, field)
        setattr(current_user, field, value)

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="profiles",
        record_id=current_user.id,
        old_values=old_values,
        new_values=data,
    )
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/refresh", response_model=Token, summary="Refresh access token")
def refresh_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> Token:
    settings = get_settings()
    try:
        token_data = jwt.decode(payload.refresh_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if token_data.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token type")
        user_id = UUID(token_data.get("sub"))
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))
    return Token(access_token=new_access, refresh_token=new_refresh)
