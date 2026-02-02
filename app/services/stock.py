from uuid import UUID

from sqlalchemy.orm import Session

from ..models import InventoryTransaction, Product


def adjust_stock(
    db: Session,
    *,
    product_id: UUID,
    quantity_delta: int,
    transaction_type: str,
    created_by: UUID,
    reference_id: UUID | None = None,
    reference_type: str | None = None,
    notes: str | None = None,
) -> tuple[Product, InventoryTransaction]:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
    if not product:
        raise ValueError("Product not found")

    product.stock_quantity = (product.stock_quantity or 0) + quantity_delta
    tx = InventoryTransaction(
        product_id=product_id,
        quantity_change=quantity_delta,
        transaction_type=transaction_type,
        reference_id=reference_id,
        reference_type=reference_type,
        created_by=created_by,
        notes=notes,
    )
    db.add(tx)
    return product, tx
