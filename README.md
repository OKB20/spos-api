# SmartPOS Backend (FastAPI)

## Setup
- Python 3.11+ recommended.
- Create virtualenv and install deps: `python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt`.
- Copy `.env.example` to `.env` and update secrets/DB URL.
- Ensure Postgres is running and accessible via `DATABASE_URL` (e.g., `postgresql+psycopg://postgres:postgres@localhost:5432/smartpos`).

## Running
- Start API: `uvicorn app.main:app --reload`.
- Docs: visit `/docs`.
- For idempotent sales, send header `X-Idempotency-Key` (or include `idempotency_key` in body) on `/api/pos/sales`.
- Refresh token: `POST /api/auth/refresh` with body `{"refresh_token": "<token>"}`.
- Quick checks: `bash scripts/check.sh` (compiles code, runs pytest).
- Postman collection: see `Backend/docs/postman_collection.json` (update `base_url` and `token` variables).

### Example requests (curl)
- Login: `curl -X POST http://localhost:8000/api/auth/login -d "username=user@example.com" -d "password=secret"`
- Create product: `curl -X POST http://localhost:8000/api/pos/products -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"name":"Item","price":10,"stock_quantity":5}'`
- Idempotent sale: `curl -X POST http://localhost:8000/api/pos/sales -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -H "X-Idempotency-Key: sale-123" -d '{"subtotal":100,"total_amount":100,"payment_method":"cash","items":[{"product_id":"<uuid>","quantity":1,"unit_price":100,"total_price":100}]}'`

## Migrations
- Init DB (first run): `alembic upgrade head`.
- Create a new migration after model changes: `alembic revision --autogenerate -m "describe change"` then `alembic upgrade head`.

## Available route groups (all prefixed with `/api/pos` unless noted)
- `/api/health` (no auth)
- Auth: `/api/auth/register`, `/api/auth/login`, `/api/auth/me`
- Products: `/products`
- Customers: `/customers`
- Sales: `/sales`
- Returns: `/returns`
- Purchases: `/purchases`
- Inventory: `/inventory/transactions`, `/inventory/counts`, `/inventory/alerts`
- Promotions: `/promotions`
- Settings: `/settings`
- Audit logs: `/audit-logs`
- Reports: `/reports/summary`

## Testing auth quickly
- Register: `POST /api/auth/register` with JSON body `{ "email": "...", "password": "password123", "role": "admin" }`.
- Login: `POST /api/auth/login` (form data `username`, `password`) to get access/refresh tokens.
- Authenticated example: `GET /api/pos/products` with header `Authorization: Bearer <access_token>`.
