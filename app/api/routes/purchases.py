from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ...api.deps import require_role
from ...db import get_db
from ...models import Product, Purchase, PurchaseItem, User
from ...schemas import PurchaseBase, PurchaseCreate, PurchaseUpdate
from ...services.audit import record_audit
from ...services.stock import adjust_stock

router = APIRouter(prefix="/purchases", tags=["purchases"])


@router.get("/", response_model=List[PurchaseBase])
def list_purchases(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("purchases.read",))),
):
    return (
        db.query(Purchase)
        .options(joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .order_by(Purchase.created_at.desc())
        .limit(200)
        .all()
    )


@router.post("/", response_model=PurchaseBase, status_code=status.HTTP_201_CREATED)
def create_purchase(
    purchase_in: PurchaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("purchases.write",))),
):
    product_ids = [item.product_id for item in purchase_in.items]
    products = {
        p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).with_for_update()
    }
    for pid in product_ids:
        if pid not in products:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not found")
    for item in purchase_in.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be positive")
        if item.unit_price < 0 or item.total_price < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prices must be non-negative")

    purchase = Purchase(
        supplier_name=purchase_in.supplier_name,
        total_amount=purchase_in.total_amount,
        purchase_date=purchase_in.purchase_date,
        status=purchase_in.status,
        notes=purchase_in.notes,
    )
    db.add(purchase)
    db.flush()

    for item_in in purchase_in.items:
        item = PurchaseItem(
            purchase_id=purchase.id,
            product_id=item_in.product_id,
            quantity=item_in.quantity,
            unit_price=item_in.unit_price,
            total_price=item_in.total_price,
        )
        db.add(item)
        _product, _tx = adjust_stock(
            db,
            product_id=item_in.product_id,
            quantity_delta=item_in.quantity,
            transaction_type="purchase",
            created_by=current_user.id,
            reference_id=purchase.id,
            reference_type="purchase",
        )

    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="purchases",
        record_id=purchase.id,
        new_values={"supplier": purchase.supplier_name, "total_amount": str(purchase.total_amount)},
    )

    db.commit()
    db.refresh(purchase)
    return purchase


@router.get("/{purchase_id}", response_model=PurchaseBase)
def get_purchase(
    purchase_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("purchases.read",))),
):
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.items).joinedload(PurchaseItem.product))
        .filter(Purchase.id == purchase_id)
        .first()
    )
    if not purchase:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")
    return purchase


@router.patch("/{purchase_id}", response_model=PurchaseBase)
def update_purchase(
    purchase_id: UUID,
    updates: PurchaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("purchases.write",))),
):
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.items))
        .filter(Purchase.id == purchase_id)
        .with_for_update()
        .first()
    )
    if not purchase:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")

    old_values = {"status": purchase.status, "notes": purchase.notes, "total_amount": str(purchase.total_amount)}

    data = updates.model_dump(exclude_unset=True)
    new_items = data.pop("items", None)

    for field, value in data.items():
        setattr(purchase, field, value)

    if new_items is not None:
        # compute stock deltas: remove old items, add new ones
        delta_map: dict[UUID, int] = {}
        for item in purchase.items:
            delta_map[item.product_id] = delta_map.get(item.product_id, 0) - item.quantity
        db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase.id).delete(synchronize_session=False)

        total_amount = 0
        for item_in in new_items:
            quantity = item_in["quantity"] if isinstance(item_in, dict) else item_in.quantity
            unit_price = item_in["unit_price"] if isinstance(item_in, dict) else item_in.unit_price
            total_price = item_in["total_price"] if isinstance(item_in, dict) else item_in.total_price
            product_id = item_in["product_id"] if isinstance(item_in, dict) else item_in.product_id

            if quantity <= 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be positive")
            if unit_price < 0 or total_price < 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prices must be non-negative")
            total_amount += total_price
            db.add(
                PurchaseItem(
                    purchase_id=purchase.id,
                    product_id=product_id,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price,
                )
            )
            delta_map[product_id] = delta_map.get(product_id, 0) + quantity

        purchase.total_amount = total_amount

        for pid, delta in delta_map.items():
            if delta != 0:
                _product, _tx = adjust_stock(
                    db,
                    product_id=pid,
                    quantity_delta=delta,
                    transaction_type="purchase_adjustment",
                    created_by=current_user.id,
                    reference_id=purchase.id,
                    reference_type="purchase",
                    notes="Purchase update",
                )

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="purchases",
        record_id=purchase.id,
        old_values=old_values,
        new_values={
            "status": purchase.status,
            "notes": purchase.notes,
            "total_amount": str(purchase.total_amount),
            "items_updated": new_items is not None,
        },
    )
    db.commit()
    db.refresh(purchase)
    return purchase
