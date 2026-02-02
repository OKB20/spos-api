import csv
from io import StringIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...api.deps import require_role
from ...db import get_db
from ...models import Product, User
from ...schemas import ProductBase, ProductCreate, ProductUpdate
from ...services.audit import record_audit

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/", response_model=List[ProductBase])
def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", "employee", allow_perms=("products.read",))),
) -> List[ProductBase]:
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()  # noqa: E712
    return products


@router.post("/", response_model=ProductBase, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("products.write",))),
) -> ProductBase:
    product = Product(**product_in.model_dump())
    db.add(product)
    record_audit(
        db,
        user_id=current_user.id,
        action="CREATE",
        table_name="products",
        record_id=product.id,
        new_values={"name": product.name, "price": str(product.price)},
    )
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductBase)
def update_product(
    product_id: UUID,
    updates: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("products.write",))),
) -> ProductBase:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    old_values = {
        "name": product.name,
        "price": str(product.price),
        "stock_quantity": product.stock_quantity,
        "cost": str(product.cost) if product.cost else None,
    }
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    record_audit(
        db,
        user_id=current_user.id,
        action="UPDATE",
        table_name="products",
        record_id=product.id,
        old_values=old_values,
        new_values=updates.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("products.delete",))),
):
    product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Soft delete to preserve references
    product.is_active = False
    db.commit()

    try:
        record_audit(
            db,
            user_id=current_user.id,
            action="DELETE",
            table_name="products",
            record_id=product.id,
            old_values={"is_active": True},
            new_values={"is_active": False},
        )
        db.commit()
    except Exception:
        db.rollback()
    return None


@router.get("/export")
def export_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("products.read",))),
):
    products = db.query(Product).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["id", "name", "price", "cost", "sku", "barcode", "stock_quantity", "is_active"]
    )

    for p in products:
        writer.writerow(
            [
                str(p.id),
                p.name,
                str(p.price),
                str(p.cost) if p.cost else "",
                p.sku or "",
                p.barcode or "",
                p.stock_quantity,
                p.is_active,
            ]
        )

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products.csv"},
    )


@router.post("/import")
async def import_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", allow_perms=("products.write",))),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    content = await file.read()
    string_content = content.decode("utf-8")
    reader = csv.DictReader(StringIO(string_content))

    for row in reader:
        sku = row.get("sku")
        barcode = row.get("barcode")

        product = None
        if sku:
            product = db.query(Product).filter(Product.sku == sku).first()
        elif barcode:
            product = db.query(Product).filter(Product.barcode == barcode).first()

        try:
            if product:
                product.name = row.get("name", product.name)
                product.price = float(row.get("price", product.price))
                if row.get("cost"):
                    product.cost = float(row.get("cost"))
                product.stock_quantity = int(row.get("stock_quantity", product.stock_quantity))
            else:
                new_product = Product(
                    name=row.get("name"),
                    price=float(row.get("price", 0)),
                    cost=float(row.get("cost")) if row.get("cost") else None,
                    sku=sku,
                    barcode=barcode,
                    stock_quantity=int(row.get("stock_quantity", 0)),
                )
                db.add(new_product)
        except (ValueError, TypeError):
            continue

    db.commit()
    return {"message": "Import successful"}
