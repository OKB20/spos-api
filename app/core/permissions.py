from typing import Iterable


DEFAULT_ROLE_PERMISSIONS: dict[str, Iterable[str]] = {
    "employee": (
        "sales.read",
        "sales.create",
        "products.read",
        "customers.read",
        "customers.write",
        "promotions.read",
        "inventory.alerts.read",
        "reports.read",
        "reports.insights.read",
        "settings.read",
    ),
    "manager": (
        "sales.read",
        "sales.create",
        "products.read",
        "products.write",
        "products.delete",
        "customers.read",
        "customers.write",
        "inventory.read",
        "inventory.count",
        "inventory.adjust",
        "inventory.alerts.read",
        "purchases.read",
        "purchases.write",
        "returns.read",
        "returns.create",
        "returns.approve",
        "promotions.read",
        "promotions.write",
        "reports.read",
        "reports.insights.read",
        "settings.read",
        "users.read",
    ),
}


def get_default_permissions(role: str | None) -> set[str]:
    if not role:
        return set()
    return set(DEFAULT_ROLE_PERMISSIONS.get(role, ()))
