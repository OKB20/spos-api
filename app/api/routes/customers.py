from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...db import get_db
from ...models import Customer, User, Sale
from ...schemas import CustomerBase, CustomerCreate, CustomerUpdate, SaleRead
from ...services.audit import record_audit

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/", response_model=List[CustomerBase])
def list_customers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("customers.read",))),
) -> List[CustomerBase]:
    return db.query(Customer).order_by(Customer.name).all()


@router.post("/", response_model=CustomerBase, status_code=status.HTTP_201_CREATED)
def create_customer(
    customer_in: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("customers.write",))),
) -> CustomerBase:
    customer = Customer(**customer_in.model_dump())
    db.add(customer)
    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="customers",
        record_id=customer.id,
        new_values={"name": customer.name, "email": customer.email},
    )
    db.commit()
    db.refresh(customer)
    return customer


@router.patch("/{customer_id}", response_model=CustomerBase)
def update_customer(
    customer_id: UUID,
    updates: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("customers.write",))),
) -> CustomerBase:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    old_values = {
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "customer_type": customer.customer_type,
    }
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="customers",
        record_id=customer.id,
        old_values=old_values,
        new_values=updates.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}/history", response_model=List[SaleRead])
def get_customer_history(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("customers.read",))),
) -> List[SaleRead]:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    return (
        db.query(Sale)
        .filter(Sale.customer_id == customer_id)
        .order_by(Sale.sale_date.desc())
        .all()
    )
