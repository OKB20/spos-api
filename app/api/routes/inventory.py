from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...db import get_db
from ...models import ExpirationAlert, InventoryCount, InventoryTransaction, Product, User
from ...schemas import (
    ExpirationAlertBase,
    InventoryCountBase,
    InventoryCountCreate,
    InventoryCountUpdate,
    InventoryTransactionBase,
    InventoryTransactionCreate,
)
from ...services.audit import record_audit
from ...services.stock import adjust_stock

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/transactions", response_model=List[InventoryTransactionBase])
def list_transactions(
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("inventory.read",))),
):
    limit = max(1, min(limit, 500))
    return (
        db.query(InventoryTransaction)
        .order_by(InventoryTransaction.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/transactions", response_model=InventoryTransactionBase, status_code=status.HTTP_201_CREATED)
def create_transaction(
    tx_in: InventoryTransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("inventory.adjust",))),
):
    product = db.query(Product).filter(Product.id == tx_in.product_id).with_for_update().first()
    if not product:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not found")
    if tx_in.quantity_change == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity change cannot be zero")

    _product, tx = adjust_stock(
        db,
        product_id=tx_in.product_id,
        quantity_delta=tx_in.quantity_change,
        transaction_type=tx_in.transaction_type,
        created_by=current_user.id,
        reference_id=tx_in.reference_id,
        reference_type=tx_in.reference_type,
        notes=tx_in.notes,
    )
    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="inventory_transactions",
        record_id=tx.id,
        new_values={"delta": tx_in.quantity_change},
    )
    db.commit()
    db.refresh(tx)
    return tx


@router.get("/counts", response_model=List[InventoryCountBase])
def list_counts(
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("inventory.count",))),
):
    limit = max(1, min(limit, 500))
    return db.query(InventoryCount).order_by(InventoryCount.updated_at.desc()).limit(limit).all()


@router.post("/counts", response_model=InventoryCountBase, status_code=status.HTTP_201_CREATED)
def create_count(
    count_in: InventoryCountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("inventory.count",))),
):
    product: Optional[Product] = None
    if count_in.product_id:
        product = (
            db.query(Product).filter(Product.id == count_in.product_id).with_for_update().first()
        )
        if not product:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not found")

    count = InventoryCount(
        product_id=count_in.product_id,
        physical_count=count_in.physical_count,
        system_count=count_in.system_count,
        difference=count_in.difference,
        status=count_in.status,
        count_date=count_in.count_date,
    )
    db.add(count)

    if product:
        delta = count_in.physical_count - (product.stock_quantity or 0)
        if delta != 0:
            _product, _tx = adjust_stock(
                db,
                product_id=product.id,
                quantity_delta=delta,
                transaction_type="stock_adjustment",
                created_by=current_user.id,
                reference_id=count.id,
                reference_type="inventory_count",
                notes="Reconciliation",
            )

    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="inventory_counts",
        record_id=count.id,
        new_values={"product_id": str(count_in.product_id) if count_in.product_id else None},
    )
    db.commit()
    db.refresh(count)
    return count


@router.patch("/counts/{count_id}", response_model=InventoryCountBase)
def update_count(
    count_id: UUID,
    count_update: InventoryCountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("inventory.count",))),
):
    count = db.query(InventoryCount).filter(InventoryCount.id == count_id).first()
    if not count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Count not found")

    old_values = {
        "physical_count": count.physical_count,
        "status": count.status,
    }
    
    update_data = count_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(count, field, value)

    # Re-calculate difference if physical or system count changed
    if "physical_count" in update_data or "system_count" in update_data:
        count.difference = (count.physical_count or 0) - (count.system_count or 0)

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="inventory_counts",
        record_id=count.id,
        old_values=old_values,
        new_values=update_data,
    )
    db.commit()
    db.refresh(count)
    return count


@router.delete("/counts/{count_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_count(
    count_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("inventory.count",))),
):
    count = db.query(InventoryCount).filter(InventoryCount.id == count_id).first()
    if not count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Count not found")

    record_audit(
        db,
        user_id=current_user.id,
        action="DELETE",
        table_name="inventory_counts",
        record_id=count.id,
        old_values={"product_id": str(count.product_id), "status": count.status},
    )
    db.delete(count)
    db.commit()
    return None


@router.get("/alerts", response_model=List[ExpirationAlertBase])
def list_expiration_alerts(
    months_ahead: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("admin", "manager", allow_perms=("inventory.alerts.read",))
    ),
):
    cutoff_days = max(1, months_ahead) * 30
    alerts = (
        db.query(ExpirationAlert)
        .filter(ExpirationAlert.alert_date <= func.current_date() + cutoff_days)
        .order_by(ExpirationAlert.alert_date.asc())
        .all()
    )
    return alerts
