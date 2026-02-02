import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.core.security import get_password_hash
from app.main import app
from app.models import Base, User


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
    user = User(
        email="auth@test.com",
        hashed_password=get_password_hash("pass1234"),
        role="employee",
    )
    db.add(user)
    db.commit()
    db.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def login(client: TestClient):
    return client.post(
        "/api/auth/login",
        data={"username": "auth@test.com", "password": "pass1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_login_and_me(client):
    resp = login(client)
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    assert tokens.get("access_token")
    assert tokens.get("refresh_token")

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == "auth@test.com"


def test_refresh_token_success(client):
    resp = login(client)
    tokens = resp.json()
    refresh = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 200, refresh.text
    payload = refresh.json()
    assert payload.get("access_token")
    assert payload.get("refresh_token")


def test_refresh_token_invalid(client):
    resp = client.post("/api/auth/refresh", json={"refresh_token": "invalid"})
    assert resp.status_code == 401, resp.text
