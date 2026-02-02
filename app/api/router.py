from fastapi import APIRouter

from .routes import (
    audit_logs,
    auth,
    customers,
    health,
    inventory,
    products,
    promotions,
    purchases,
    reports,
    returns,
    sales,
    settings,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(products.router, prefix="/pos")
api_router.include_router(customers.router, prefix="/pos")
api_router.include_router(sales.router, prefix="/pos")
api_router.include_router(returns.router, prefix="/pos")
api_router.include_router(purchases.router, prefix="/pos")
api_router.include_router(inventory.router, prefix="/pos")
api_router.include_router(promotions.router, prefix="/pos")
api_router.include_router(settings.router, prefix="/pos")
api_router.include_router(audit_logs.router, prefix="/pos")
api_router.include_router(reports.router, prefix="/pos")
api_router.include_router(users.router)
