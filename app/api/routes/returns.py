from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ...api.deps import require_role
from ...db import get_db
from ...models import Product, Return, Sale, SaleItem, User
from ...schemas import ReturnBase, ReturnCreate, ReturnUpdate
from ...services.audit import record_audit
from ...services.stock import adjust_stock

router = APIRouter(prefix="/returns", tags=["returns"])


@router.get("/", response_model=list[ReturnBase])
def list_returns(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("returns.read",))),
):
    return (
        db.query(Return)
        .options(joinedload(Return.sale))
        .order_by(Return.created_at.desc())
        .limit(200)
        .all()
    )


@router.post("/", response_model=ReturnBase, status_code=status.HTTP_201_CREATED)
def create_return(
    ret_in: ReturnCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("returns.create",))),
):
    sale = db.query(Sale).filter(Sale.id == ret_in.sale_id).first()
    if not sale:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sale not found")
    product = db.query(Product).filter(Product.id == ret_in.product_id).with_for_update().first()
    if not product:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not found")

    sale_item = (
        db.query(SaleItem)
        .filter(SaleItem.sale_id == ret_in.sale_id, SaleItem.product_id == ret_in.product_id)
        .first()
    )
    if not sale_item:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not in sale")
    if ret_in.quantity <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be positive")
    if ret_in.refund_amount < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Refund must be non-negative")

    ret = Return(
        sale_id=ret_in.sale_id,
        product_id=ret_in.product_id,
        processed_by=current_user.id,
        quantity=ret_in.quantity,
        reason=ret_in.reason,
        refund_amount=ret_in.refund_amount,
        status=ret_in.status,
    )
    db.add(ret)
    _product, _tx = adjust_stock(
        db,
        product_id=ret_in.product_id,
        quantity_delta=ret_in.quantity,
        transaction_type="return",
        created_by=current_user.id,
        reference_id=ret.id,
        reference_type="return",
    )
    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="returns",
        record_id=ret.id,
        new_values={"sale_id": str(ret_in.sale_id), "product_id": str(ret_in.product_id)},
    )
    db.commit()
    db.refresh(ret)
    return ret


@router.patch("/{return_id}", response_model=ReturnBase)
def update_return(
    return_id: UUID,
    updates: ReturnUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("returns.approve",))),
):
    ret = db.query(Return).filter(Return.id == return_id).first()
    if not ret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Return not found")

    old_status = ret.status
    if updates.status is not None:
        ret.status = updates.status

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="returns",
        record_id=ret.id,
        old_values={"status": old_status},
        new_values={"status": ret.status},
    )
    db.commit()
    db.refresh(ret)
    return ret


@router.get("/{return_id}", response_model=ReturnBase)
def get_return(
    return_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("returns.read",))),
):
    ret = (
        db.query(Return)
        .options(joinedload(Return.sale))
        .filter(Return.id == return_id)
        .first()
    )
    if not ret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Return not found")
    return ret
