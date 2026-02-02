from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...db import get_db
from ...models import Promotion, User
from ...schemas import PromotionBase, PromotionCreate, PromotionUpdate
from ...services.audit import record_audit

router = APIRouter(prefix="/promotions", tags=["promotions"])


@router.get("/", response_model=List[PromotionBase])
def list_promotions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("promotions.read",))),
):
    return db.query(Promotion).order_by(Promotion.created_at.desc()).all()


@router.post("/", response_model=PromotionBase, status_code=status.HTTP_201_CREATED)
def create_promotion(
    promo_in: PromotionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("promotions.write",))),
):
    promo = Promotion(**promo_in.model_dump())
    db.add(promo)
    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="promotions",
        record_id=promo.id,
        new_values={"name": promo.name, "type": promo.type},
    )
    db.commit()
    db.refresh(promo)
    return promo


@router.patch("/{promotion_id}", response_model=PromotionBase)
def update_promotion(
    promotion_id: UUID,
    updates: PromotionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("promotions.write",))),
):
    promo = db.query(Promotion).filter(Promotion.id == promotion_id).first()
    if not promo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion not found")

    old_values = {
        "name": promo.name,
        "type": promo.type,
        "value": float(promo.value),
        "is_active": promo.is_active,
    }
    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(promo, field, value)

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="promotions",
        record_id=promo.id,
        old_values=old_values,
        new_values=update_data,
    )
    db.commit()
    db.refresh(promo)
    return promo
