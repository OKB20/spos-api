from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.core.security import get_password_hash
from app.db import get_db
from app.main import app
from app.models import Base, Customer, Product, Sale, SaleItem, User


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

CURRENT_USER_ID = None
USER_IDS: dict[str, str] = {}


@pytest.fixture(scope="module")
def client():
    global CURRENT_USER_ID, USER_IDS
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    admin = User(
        email="admin@local.com",
        hashed_password=get_password_hash("pass1234"),
        role="admin",
    )
    manager = User(
        email="manager@local.com",
        hashed_password=get_password_hash("pass1234"),
        role="manager",
    )
    employee = User(
        email="employee@local.com",
        hashed_password=get_password_hash("pass1234"),
        role="employee",
    )
    denied_employee = User(
        email="denied@local.com",
        hashed_password=get_password_hash("pass1234"),
        role="employee",
        permissions={"allow": [], "deny": ["reports.insights.read"]},
    )

    product = Product(
        name="Widget",
        price=10,
        cost=5,
        stock_quantity=1,
        min_stock_level=5,
    )
    customer = Customer(name="VIP Customer", customer_type="vip")

    db.add_all([admin, manager, employee, denied_employee, product, customer])
    db.commit()

    sale = Sale(
        sale_number="S-TEST-1",
        cashier_id=admin.id,
        customer_id=customer.id,
        subtotal=10,
        total_amount=10,
        payment_method="cash",
        sale_date=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.add(sale)
    db.flush()
    sale_item = SaleItem(
        sale_id=sale.id,
        product_id=product.id,
        quantity=1,
        unit_price=10,
        total_price=10,
    )
    db.add(sale_item)
    db.commit()

    USER_IDS = {
        "admin": str(admin.id),
        "manager": str(manager.id),
        "employee": str(employee.id),
        "denied_employee": str(denied_employee.id),
    }
    CURRENT_USER_ID = admin.id
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
            user_id = CURRENT_USER_ID or admin.id
            return db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def set_current_user(user_key: str):
    global CURRENT_USER_ID
    CURRENT_USER_ID = uuid.UUID(USER_IDS[user_key])


@pytest.mark.parametrize(
    "path, expected_keys",
    [
        ("/api/pos/reports/insights", ["opportunities", "attention_points", "generated_at"]),
        ("/api/pos/reports/analytics", ["monthly_series", "customer_segments", "product_performance", "metrics"]),
        ("/api/pos/reports/predictions", ["sales_predictions", "stock_predictions", "market_trends"]),
        ("/api/pos/reports/recommendations", ["quick_wins", "performance"]),
    ],
)
def test_ai_report_endpoints_admin_allowed(client, path, expected_keys):
    set_current_user("admin")
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in expected_keys:
        assert key in body


def test_ai_chat_endpoints_admin_allowed(client):
    set_current_user("admin")
    resp = client.post("/api/pos/reports/chat", json={"message": "ventes"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "response" in body
    assert isinstance(body.get("suggestions"), list)

    suggestions = client.get("/api/pos/reports/chat/suggestions")
    assert suggestions.status_code == 200, suggestions.text
    assert isinstance(suggestions.json().get("suggestions"), list)


def test_reports_permission_denied_with_explicit_block(client):
    set_current_user("denied_employee")
    resp = client.get("/api/pos/reports/analytics")
    assert resp.status_code == 403, resp.text


def test_reports_permission_allowed_for_employee_default(client):
    set_current_user("employee")
    resp = client.get("/api/pos/reports/analytics")
    assert resp.status_code == 200, resp.text


def test_users_list_permissions(client):
    set_current_user("employee")
    resp = client.get("/api/users")
    assert resp.status_code == 403, resp.text

    set_current_user("manager")
    resp = client.get("/api/users")
    assert resp.status_code == 200, resp.text


def test_users_patch_requires_admin(client):
    set_current_user("manager")
    resp = client.patch(f"/api/users/{USER_IDS['employee']}", json={"role": "manager"})
    assert resp.status_code == 403, resp.text

    set_current_user("admin")
    resp = client.patch(f"/api/users/{USER_IDS['employee']}", json={"role": "manager"})
    assert resp.status_code == 200, resp.text
