import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_current_user
from app.db import get_db
from app.core.security import get_password_hash
from app.models import Base, Product, Purchase, Sale, SaleItem, User


# Shared in-memory SQLite database for fast, isolated tests
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def client():
    # Create schema and seed a single admin user + product
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    admin = User(
        email="admin@test.com",
        hashed_password=get_password_hash("pass1234"),
        role="admin",
    )
    product = Product(name="Test Product", price=10, stock_quantity=0)
    db.add(admin)
    db.add(product)
    db.commit()
    admin_id = admin.id
    db.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def override_get_current_user():
        db = TestingSessionLocal()
        try:
            return db.query(User).filter(User.id == admin_id).first()
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_purchase_patch_updates_status_and_items(client):
    db = TestingSessionLocal()
    product_id = str(db.query(Product).first().id)
    db.close()

    # Create a purchase
    create_resp = client.post(
        "/api/pos/purchases",
        json={
            "supplier_name": "Supplier A",
            "total_amount": 20,
            "status": "pending",
            "items": [
                {
                    "product_id": product_id,
                    "quantity": 2,
                    "unit_price": 10,
                    "total_price": 20,
                }
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    purchase = create_resp.json()

    # Patch purchase with new quantity and status
    patch_resp = client.patch(
        f"/api/pos/purchases/{purchase['id']}",
        json={
            "status": "received",
            "notes": "Updated items",
            "items": [
                {
                    "product_id": product_id,
                    "quantity": 3,
                    "unit_price": 10,
                    "total_price": 30,
                }
            ],
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patched = patch_resp.json()
    assert patched["status"] == "received"
    assert float(patched["total_amount"]) == 30.0

    # Stock should reflect the updated quantity (delta applied)
    db = TestingSessionLocal()
    updated_product = db.query(Product).filter(Product.id == uuid.UUID(product_id)).first()
    db.close()
    assert updated_product.stock_quantity == 3


def test_return_patch_status(client):
    db = TestingSessionLocal()
    admin_id = db.query(User).first().id
    product_id = db.query(Product).first().id
    sale = Sale(
        sale_number="S-" + uuid.uuid4().hex[:6],
        cashier_id=admin_id,
        subtotal=10,
        total_amount=10,
        payment_method="cash",
    )
    db.add(sale)
    db.flush()
    sale_item = SaleItem(
        sale_id=sale.id,
        product_id=product_id,
        quantity=1,
        unit_price=10,
        total_price=10,
    )
    db.add(sale_item)
    db.commit()
    db.refresh(sale)
    db.close()

    create_resp = client.post(
        "/api/pos/returns",
            json={
                "sale_id": str(sale.id),
                "product_id": str(product_id),
                "processed_by": str(admin_id),
                "quantity": 1,
                "reason": "Defect",
                "refund_amount": 10,
                "status": "pending",
            },
    )
    assert create_resp.status_code == 201, create_resp.text
    ret = create_resp.json()

    patch_resp = client.patch(f"/api/pos/returns/{ret['id']}", json={"status": "approved"})
    assert patch_resp.status_code == 200, patch_resp.text
    patched = patch_resp.json()
    assert patched["status"] == "approved"


def test_user_role_patch(client):
    # Reuse seeded admin and change the role to ensure the endpoint updates correctly
    db = TestingSessionLocal()
    admin_id = db.query(User).filter(User.email == "admin@test.com").first().id
    db.close()

    resp = client.patch(f"/api/users/{admin_id}", json={"role": "manager"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "manager"
