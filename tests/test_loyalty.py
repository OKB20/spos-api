import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.api.deps import get_current_user
from app.db import get_db
from app.core.security import get_password_hash
from app.models import Base, Product, Customer, User, SystemSetting

# Shared in-memory SQLite database
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    
    # Create Admin User
    admin = User(
        email="admin_loyalty@test.com",
        hashed_password=get_password_hash("pass1234"),
        role="admin",
    )
    
    # Create Test Product
    product = Product(
        name="Test Item", 
        price=10.0, 
        stock_quantity=100
    )

    # Create Test Customer
    customer = Customer(
        name="Loyal Customer",
        email="loyal@test.com",
        loyalty_points=0
    )
    
    db.add(admin)
    db.add(product)
    db.add(customer)
    db.commit()
    
    admin_id = admin.id
    product_id = product.id
    customer_id = customer.id
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
        yield test_client, product_id, customer_id

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)

def test_loyalty_points_accrual(client):
    c, product_id, customer_id = client
    
    # 1. Configure Loyalty Program (1 point per 1 unit of currency)
    settings_payload = {
        "setting_value": {
            "enabled": True,
            "points_per_currency": 1
        },
        "description": "Loyalty Program Test"
    }
    resp = c.put("/api/pos/settings/loyalty_program", json=settings_payload)
    assert resp.status_code == 200

    # 2. Create Sale ($100 total)
    sale_payload = {
        "customer_id": str(customer_id),
        "total_amount": 100.0,
        "subtotal": 100.0,
        "payment_method": "cash",
        "items": [
            {
                "product_id": str(product_id),
                "quantity": 10,
                "unit_price": 10.0,
                "total_price": 100.0
            }
        ]
    }
    
    sale_resp = c.post("/api/pos/sales", json=sale_payload)
    assert sale_resp.status_code == 201
    
    # 3. Verify Customer Points
    # Fetch customer details (assuming we have a GET endpoint or using direct DB check if needed, 
    # but let's try fetching via valid endpoint or simulating check)
    # Since I don't have a direct "get customer" endpoint in my memory map, I'll rely on the DB
    # or just trust the Sale response won't show it but I can check via another sale?
    # Actually, I'll check directly via DB session in test.

    db = TestingSessionLocal()
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    assert customer.loyalty_points == 100
    db.close()

def test_loyalty_disabled(client):
    c, product_id, customer_id = client
    
    # 1. Disable Program
    settings_payload = {
        "setting_value": {
            "enabled": False,
            "points_per_currency": 1
        },
        "description": "Loyalty Disabled"
    }
    c.put("/api/pos/settings/loyalty_program", json=settings_payload)

    # 2. Create Sale ($50)
    sale_payload = {
        "customer_id": str(customer_id),
        "total_amount": 50.0,
        "subtotal": 50.0,
        "payment_method": "cash",
        "items": [
            {
                "product_id": str(product_id),
                "quantity": 5,
                "unit_price": 10.0,
                "total_price": 50.0
            }
        ]
    }
    
    c.post("/api/pos/sales", json=sale_payload)
    
    # 3. Verify Points Unchanged (should still be 100 from previous test)
    db = TestingSessionLocal()
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    assert customer.loyalty_points == 100 # No new points added
    db.close()
