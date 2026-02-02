from datetime import datetime, time, timezone
from decimal import Decimal
from typing import List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ...api.deps import require_role
from ...db import get_db
from ...models import Customer, Product, Sale, SaleItem, SystemSetting, User
from ...schemas import SaleCreate, SaleRead
from ...services.audit import record_audit
from ...services.stock import adjust_stock

router = APIRouter(prefix="/sales", tags=["sales"])


def _generate_sale_number() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"SALE-{timestamp}-{uuid4().hex[:6].upper()}"


def _parse_date_time(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format") from exc
        day_time = time.max if end_of_day else time.min
        return datetime.combine(parsed.date(), day_time, tzinfo=timezone.utc)

    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid datetime format") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.get("/", response_model=List[SaleRead])
def list_sales(
    limit: int = 50,
    start_date: str | None = None,
    end_date: str | None = None,
    cashier_id: UUID | None = None,
    customer_id: UUID | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("sales.read",))),
) -> List[SaleRead]:
    limit = max(1, min(limit, 200))
    start_dt = _parse_date_time(start_date)
    end_dt = _parse_date_time(end_date, end_of_day=True)
    query = db.query(Sale).options(joinedload(Sale.items).joinedload(SaleItem.product))

    if start_dt:
        query = query.filter(Sale.sale_date >= start_dt)
    if end_dt:
        query = query.filter(Sale.sale_date <= end_dt)
    if cashier_id:
        query = query.filter(Sale.cashier_id == cashier_id)
    if customer_id:
        query = query.filter(Sale.customer_id == customer_id)
    if status:
        query = query.filter(Sale.status == status)

    sales = query.order_by(Sale.created_at.desc()).limit(limit).all()
    return sales


@router.get("/{sale_id}", response_model=SaleRead)
def get_sale(
    sale_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("sales.read",))),
) -> SaleRead:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items).joinedload(SaleItem.product))
        .filter(Sale.id == sale_id)
        .first()
    )
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    return sale


@router.post("/", response_model=SaleRead, status_code=status.HTTP_201_CREATED)
def create_sale(
    sale_in: SaleCreate,
    x_idempotency_key: str | None = Header(default=None, convert_underscores=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "employee", allow_perms=("sales.create",))),
) -> SaleRead:
    idem_key = x_idempotency_key or sale_in.idempotency_key
    if idem_key:
        existing = db.query(Sale).filter(Sale.idempotency_key == idem_key).first()
        if existing:
            return existing

    # Basic stock validation
    product_ids = [item.product_id for item in sale_in.items]
    products = {
        p.id: p
        for p in db.query(Product)
        .filter(Product.id.in_(product_ids))
        .with_for_update()
    }
    for item in sale_in.items:
        product = products.get(item.product_id)
        if not product:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product not found")
        if (product.stock_quantity or 0) < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for product {product.name}",
            )

    computed_total = sum([item.total_price for item in sale_in.items])
    if abs(computed_total - sale_in.total_amount) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Total amount does not match sum of item totals",
        )
    if sale_in.payment_method not in {"cash", "card", "mobile", "other"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment_method")
    if sale_in.payment_status and sale_in.payment_status not in {"paid", "pending", "refunded"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment_status")
    for item in sale_in.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be positive")
        if item.total_price < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Total price must be non-negative")

    sale = Sale(
        sale_number=_generate_sale_number(),
        idempotency_key=idem_key,
        cashier_id=current_user.id,
        customer_id=sale_in.customer_id,
        subtotal=sale_in.subtotal,
        tax_amount=sale_in.tax_amount,
        discount_amount=sale_in.discount_amount,
        total_amount=sale_in.total_amount,
        payment_method=sale_in.payment_method,
        payment_status=sale_in.payment_status,
        notes=sale_in.notes,
        sale_date=datetime.now(timezone.utc),
    )
    db.add(sale)
    db.flush()

    items: List[SaleItem] = []
    for item_in in sale_in.items:
        item = SaleItem(
            sale_id=sale.id,
            product_id=item_in.product_id,
            quantity=item_in.quantity,
            unit_price=item_in.unit_price,
            discount_amount=item_in.discount_amount,
            total_price=item_in.total_price,
        )
        db.add(item)
        items.append(item)
        _product, _tx = adjust_stock(
            db,
            product_id=item_in.product_id,
            quantity_delta=-item_in.quantity,
            transaction_type="sale",
            created_by=current_user.id,
            reference_id=sale.id,
            reference_type="sale",
        )

    record_audit(
        db=db,
        user_id=current_user.id,
        action="CREATE",
        table_name="sales",
        record_id=sale.id,
        new_values={
            "sale_number": sale.sale_number,
            "total_amount": sale.total_amount,
            "items": [
                {"product_id": str(i.product_id), "qty": i.quantity, "total": float(i.total_price)}
                for i in items
            ],
        },
    )

    # Update Customer totals
    if sale.customer_id:
        customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
        if customer:
            total_purchases = Decimal(str(customer.total_purchases or 0))
            sale_total = Decimal(str(sale.total_amount))
            customer.total_purchases = total_purchases + sale_total
            customer.last_purchase_date = sale.sale_date

            # Calculate Loyalty Points
            loyalty_setting = db.query(SystemSetting).filter(SystemSetting.setting_key == "loyalty_program").first()
            if loyalty_setting and loyalty_setting.setting_value.get("enabled", False):
                # Handle Redemption first (deduct points)
                if sale_in.points_redeemed and sale_in.points_redeemed > 0:
                    if (customer.loyalty_points or 0) < sale_in.points_redeemed:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST, 
                            detail=f"Insufficient loyalty points. Available: {customer.loyalty_points}"
                        )
                    customer.loyalty_points -= sale_in.points_redeemed

                # Handle Accrual (earn points on SUBTOTAL, not total)
                # This ensures customers don't earn points on discounted amounts
                points_ratio = float(loyalty_setting.setting_value.get("points_per_currency", 1.0))
                subtotal_for_points = Decimal(str(sale.subtotal))
                points_earned = int(subtotal_for_points * Decimal(str(points_ratio)))
                customer.loyalty_points = (customer.loyalty_points or 0) + points_earned

    db.commit()
    db.refresh(sale)
    sale.items = items
    return sale


@router.patch("/{sale_id}/void", response_model=SaleRead)
def void_sale(
    sale_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("sales.void",))),
) -> SaleRead:
    sale = (
        db.query(Sale)
        .options(joinedload(Sale.items))
        .filter(Sale.id == sale_id)
        .first()
    )
    if not sale:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found")
    if sale.status == "voided":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sale already voided")

    sale.status = "voided"

    # Reverse stock
    for item in sale.items:
        adjust_stock(
            db,
            product_id=item.product_id,
            quantity_delta=item.quantity,
            transaction_type="sale_void",
            created_by=current_user.id,
            reference_id=sale.id,
            reference_type="sale",
            notes=f"Voiding sale {sale.sale_number}",
        )

    record_audit(
        db=db,
        user_id=current_user.id,
        action="VOID",
        table_name="sales",
        record_id=sale.id,
        new_values={"status": "voided", "sale_number": sale.sale_number},
    )

    # Update Customer totals (reverse)
    if sale.customer_id:
        customer = db.query(Customer).filter(Customer.id == sale.customer_id).first()
        if customer:
            total_purchases = Decimal(str(customer.total_purchases or 0))
            sale_total = Decimal(str(sale.total_amount))
            customer.total_purchases = total_purchases - sale_total

    db.commit()
    db.refresh(sale)
    return sale
