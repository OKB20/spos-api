from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, selectinload

from ...api.deps import require_role
from ...db import get_db
from ...models import Customer, Product, Sale, SaleItem, User
from ...schemas import (
    AIAnalyticsCustomerSegment,
    AIAnalyticsMetrics,
    AIAnalyticsProductPerformance,
    AIAnalyticsResponse,
    AIAnalyticsMonthlyPoint,
    AIChatRequest,
    AIChatResponse,
    AIChatSuggestions,
    AIInsightsResponse,
    AIMarketTrend,
    AIPredictionsResponse,
    AIQuickWin,
    AIRecommendationsPerformance,
    AIRecommendationsResponse,
    AISalesPrediction,
    AIStockPrediction,
    ReportSummary,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _month_start(base: datetime, offset: int) -> datetime:
    month_index = (base.month - 1) + offset
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    return datetime(year, month, 1)


def _load_sales_window(
    db: Session, start: datetime | None = None, end: datetime | None = None
) -> list[Sale]:
    query = (
        db.query(Sale)
        .options(selectinload(Sale.items).selectinload(SaleItem.product))
        .order_by(Sale.sale_date.desc())
    )
    if start:
        query = query.filter(Sale.sale_date >= start)
    if end:
        query = query.filter(Sale.sale_date < end)
    return query.all()


def _aggregate_product_sales(sales: list[Sale], product_map: dict) -> list[dict]:
    aggregate: dict = {}
    for sale in sales:
        for item in sale.items or []:
            product = item.product or product_map.get(item.product_id)
            name = product.name if product else "Produit"
            existing = aggregate.get(item.product_id) or {
                "product_id": item.product_id,
                "name": name,
                "quantity": 0,
                "revenue": 0.0,
            }
            qty = int(item.quantity or 0)
            existing["quantity"] += qty
            existing["revenue"] += float(item.total_price or 0)
            aggregate[item.product_id] = existing
    return list(aggregate.values())


def _build_chat_suggestions(summary: dict) -> list[str]:
    suggestions: list[str] = []
    top_products = summary.get("top_products", [])
    low_stock = summary.get("low_stock", [])
    total_recent = summary.get("total_recent", 0)

    def _item_name(item: object) -> str:
        if isinstance(item, dict):
            return str(item.get("name") or "Produit")
        return str(getattr(item, "name", "Produit"))

    if top_products:
        suggestions.append(f"Quels sont les details de vente pour {_item_name(top_products[0])} ?")
    if low_stock:
        suggestions.append(f"Quand reapprovisionner {_item_name(low_stock[0])} ?")
    if total_recent > 0:
        suggestions.append("Resume des ventes des 7 derniers jours ?")
    return suggestions[:4]


@router.get("/summary", response_model=ReportSummary)
def summary(
    days: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.read",))),
):
    sales_query = db.query(Sale)
    if days:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        sales_query = sales_query.filter(Sale.sale_date >= start)
    total_sales_amount = (
        sales_query.with_entities(func.coalesce(func.sum(Sale.total_amount), 0)).scalar() or 0
    )
    total_sales_count = sales_query.with_entities(func.count(Sale.id)).scalar() or 0
    total_products = db.query(func.count(Product.id)).scalar() or 0
    inventory_value = (
        db.query(
            func.coalesce(
                func.sum((Product.stock_quantity) * func.coalesce(Product.cost, 0)), 0
            )
        ).scalar()
        or 0
    )
    return ReportSummary(
        total_sales_amount=float(total_sales_amount),
        total_sales_count=total_sales_count,
        total_products=total_products,
        total_inventory_value=float(
            inventory_value if isinstance(inventory_value, (int, float, Decimal)) else 0
        ),
    )


@router.get("/insights", response_model=AIInsightsResponse)
def insights(
    days: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.insights.read",))),
):
    opportunities: list[str] = []
    attention_points: list[str] = []

    top_products_query = (
        db.query(Product.name, func.coalesce(func.sum(SaleItem.quantity), 0).label("qty"))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
    )
    if days:
        start = datetime.now(timezone.utc) - timedelta(days=days)
        top_products_query = top_products_query.filter(Sale.sale_date >= start)
    top_products = (
        top_products_query.group_by(Product.id, Product.name)
        .order_by(desc("qty"))
        .limit(3)
        .all()
    )
    for name, qty in top_products:
        opportunities.append(f"Augmenter le stock de \"{name}\" ({int(qty)} ventes)")

    low_stock = (
        db.query(Product.name, Product.stock_quantity, Product.min_stock_level)
        .filter(Product.min_stock_level.isnot(None))
        .filter(Product.stock_quantity <= Product.min_stock_level)
        .order_by(Product.stock_quantity.asc())
        .limit(3)
        .all()
    )
    for name, stock, min_stock in low_stock:
        attention_points.append(f"Stock faible pour \"{name}\" ({stock}/{min_stock})")

    negative_margin = (
        db.query(Product.name, Product.price, Product.cost)
        .filter(Product.cost.isnot(None))
        .filter(Product.price <= Product.cost)
        .limit(2)
        .all()
    )
    for name, price, cost in negative_margin:
        attention_points.append(f"Marge negative pour \"{name}\" (prix {price}, cout {cost})")

    return AIInsightsResponse(
        opportunities=opportunities,
        attention_points=attention_points,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/analytics", response_model=AIAnalyticsResponse)
def analytics(
    months: int | None = Query(default=None, ge=1, le=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.insights.read",))),
):
    now = datetime.now(timezone.utc)
    months_back = months or 6
    buckets: list[dict] = []
    totals: dict[str, float] = {}

    for i in range(months_back - 1, -1, -1):
        start = _month_start(now, -i)
        key = f"{start.year}-{start.month}"
        buckets.append(
            {"key": key, "label": f"{start.month}/{str(start.year)[-2:]}"}
        )
        totals[key] = 0.0

    earliest = _month_start(now, -(months_back - 1))
    monthly_sales = (
        db.query(Sale.sale_date, Sale.total_amount)
        .filter(Sale.sale_date >= earliest)
        .all()
    )
    for sale_date, total_amount in monthly_sales:
        if not sale_date:
            continue
        key = f"{sale_date.year}-{sale_date.month}"
        if key in totals:
            totals[key] += float(total_amount or 0)

    actuals = [int(round(totals[bucket["key"]])) for bucket in buckets]
    monthly_series: list[AIAnalyticsMonthlyPoint] = []
    for index, bucket in enumerate(buckets):
        prior = actuals[max(0, index - 3):index]
        predicted = int(round(sum(prior) / len(prior))) if prior else actuals[index]
        monthly_series.append(
            AIAnalyticsMonthlyPoint(
                month=bucket["label"],
                actual=actuals[index],
                predicted=predicted,
            )
        )

    segment_rows = (
        db.query(Customer.customer_type, func.count(Customer.id))
        .group_by(Customer.customer_type)
        .all()
    )
    total_customers = sum(int(count) for _, count in segment_rows) or 1
    customer_segments: list[AIAnalyticsCustomerSegment] = []
    for segment, count in segment_rows:
        name = segment.strip() if isinstance(segment, str) and segment.strip() else "Non defini"
        value = int(round((int(count) / total_customers) * 100))
        customer_segments.append(
            AIAnalyticsCustomerSegment(name=name, value=value)
        )

    products = db.query(Product).all()
    product_map = {product.id: product for product in products}
    recent_sales = _load_sales_window(db, now - timedelta(days=30))
    previous_sales = _load_sales_window(db, now - timedelta(days=60), now - timedelta(days=30))

    recent_product_sales = _aggregate_product_sales(recent_sales, product_map)
    previous_product_sales = {
        item["product_id"]: item for item in _aggregate_product_sales(previous_sales, product_map)
    }
    recent_product_sales.sort(key=lambda item: item["quantity"], reverse=True)
    top_products = recent_product_sales[:5]
    max_qty = top_products[0]["quantity"] if top_products else 1

    product_performance: list[AIAnalyticsProductPerformance] = []
    for item in top_products:
        prev_qty = previous_product_sales.get(item["product_id"], {}).get("quantity", 0)
        diff = item["quantity"] - prev_qty
        trend = "up" if diff > 0 else "down" if diff < 0 else "stable"
        performance = int(round((item["quantity"] / max_qty) * 100)) if max_qty else 0
        product_performance.append(
            AIAnalyticsProductPerformance(
                product=item["name"],
                performance=performance,
                trend=trend,
            )
        )

    total_recent = sum(float(sale.total_amount or 0) for sale in recent_sales)
    avg_sale = total_recent / len(recent_sales) if recent_sales else 0
    gross_profit = 0.0
    for sale in recent_sales:
        for item in sale.items or []:
            product = item.product or product_map.get(item.product_id)
            if not product or product.cost is None:
                continue
            revenue = float(item.total_price or 0)
            cost = float(product.cost or 0) * float(item.quantity or 0)
            gross_profit += revenue - cost
    low_stock_count = len(
        [
            product
            for product in products
            if product.min_stock_level is not None
            and product.stock_quantity <= (product.min_stock_level or 0)
        ]
    )

    metrics = AIAnalyticsMetrics(
        total_recent=int(round(total_recent)),
        avg_sale=int(round(avg_sale)),
        gross_profit=int(round(gross_profit)),
        low_stock_count=low_stock_count,
    )

    return AIAnalyticsResponse(
        monthly_series=monthly_series,
        customer_segments=customer_segments,
        product_performance=product_performance,
        metrics=metrics,
    )


@router.get("/predictions", response_model=AIPredictionsResponse)
def predictions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.insights.read",))),
):
    now = datetime.now(timezone.utc)
    products = db.query(Product).all()
    product_map = {product.id: product for product in products}

    recent_sales = _load_sales_window(db, now - timedelta(days=30))
    previous_sales = _load_sales_window(db, now - timedelta(days=60), now - timedelta(days=30))

    total_recent = sum(float(sale.total_amount or 0) for sale in recent_sales)
    total_prev = sum(float(sale.total_amount or 0) for sale in previous_sales)
    avg_daily = total_recent / 30 if total_recent else 0
    change_pct = ((total_recent - total_prev) / total_prev * 100) if total_prev > 0 else 0
    trend = "up" if change_pct > 5 else "down" if change_pct < -5 else "stable"

    active_days = len({sale.sale_date.date() for sale in recent_sales if sale.sale_date})
    confidence = int(min(95, max(40, round((active_days / 30) * 100))))

    factors: list[str] = []
    if change_pct > 5:
        factors.append("Ventes recentes au-dessus de la moyenne")
    if change_pct < -5:
        factors.append("Ventes recentes en dessous de la moyenne")
    if total_recent == 0:
        factors.append("Aucune vente recente")

    recent_product_sales = _aggregate_product_sales(recent_sales, product_map)
    recent_product_sales.sort(key=lambda item: item["quantity"], reverse=True)
    top_product = recent_product_sales[0] if recent_product_sales else None
    if top_product:
        factors.append(f"Produit dominant: {top_product['name']}")

    def _build_period(label: str, days: int) -> AISalesPrediction:
        return AISalesPrediction(
            period=label,
            prediction=f"{int(round(avg_daily * days))} HTG",
            confidence=confidence,
            trend=trend,
            change=f"{int(round(change_pct))}%",
            factors=factors[:3],
        )

    sales_predictions = [
        _build_period("7 jours", 7),
        _build_period("30 jours", 30),
        _build_period("90 jours", 90),
    ]

    stock_predictions: list[AIStockPrediction] = []
    sales_by_product = recent_product_sales
    for item in sales_by_product:
        product = product_map.get(item["product_id"])
        if not product:
            continue
        avg_daily_qty = item["quantity"] / 30 if item["quantity"] else 0
        stock = int(product.stock_quantity or 0)
        days_remaining = int(stock / avg_daily_qty) if avg_daily_qty > 0 else 0
        predicted_demand = int(round(avg_daily_qty * 7))
        if avg_daily_qty == 0:
            urgency = "low"
            recommendation = "Aucune prevision disponible"
        else:
            if days_remaining <= 3:
                urgency = "high"
                recommendation = f"Commander {max(predicted_demand - stock, 0)} unites rapidement"
            elif days_remaining <= 7:
                urgency = "medium"
                recommendation = "Planifier un reapprovisionnement"
            else:
                urgency = "low"
                recommendation = "Stock suffisant pour la semaine"

        stock_predictions.append(
            AIStockPrediction(
                product=item["name"],
                current_stock=stock,
                predicted_demand=predicted_demand,
                days_remaining=days_remaining,
                urgency=urgency,
                recommendation=recommendation,
            )
        )

    stock_predictions.sort(key=lambda item: item.days_remaining or 9999)
    stock_predictions = stock_predictions[:5]

    market_trends: list[AIMarketTrend] = []
    if total_prev > 0:
        market_trends.append(
            AIMarketTrend(
                trend="Croissance des ventes recentes"
                if change_pct >= 0
                else "Baisse des ventes recentes",
                impact="Positif" if change_pct >= 0 else "Negatif",
                probability=int(min(95, abs(round(change_pct)))),
                timeframe="30 jours",
                action="Renforcer les produits les plus vendus"
                if change_pct >= 0
                else "Verifier les ruptures et promotions",
            )
        )

    low_stock = [
        product
        for product in products
        if product.min_stock_level is not None
        and product.stock_quantity <= (product.min_stock_level or 0)
    ]
    if low_stock:
        market_trends.append(
            AIMarketTrend(
                trend=f"Risque de rupture pour {len(low_stock)} produits",
                impact="Negatif",
                probability=int(min(95, 50 + len(low_stock) * 10)),
                timeframe="7 jours",
                action=f"Prioriser {low_stock[0].name}",
            )
        )

    total_qty = sum(item["quantity"] for item in recent_product_sales) or 0
    if top_product and total_qty > 0:
        share = top_product["quantity"] / total_qty
        market_trends.append(
            AIMarketTrend(
                trend=f"Concentration des ventes sur {top_product['name']}",
                impact="Opportunite",
                probability=int(min(95, round(share * 100))),
                timeframe="30 jours",
                action=f"Mettre en avant {top_product['name']}",
            )
        )

    return AIPredictionsResponse(
        sales_predictions=sales_predictions,
        stock_predictions=stock_predictions,
        market_trends=market_trends[:3],
    )


@router.get("/recommendations", response_model=AIRecommendationsResponse)
def recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.insights.read",))),
):
    now = datetime.now(timezone.utc)
    products = db.query(Product).all()
    product_map = {product.id: product for product in products}
    recent_sales = _load_sales_window(db, now - timedelta(days=30))
    product_sales = _aggregate_product_sales(recent_sales, product_map)
    product_sales.sort(key=lambda item: item["quantity"], reverse=True)

    low_stock = [
        product
        for product in products
        if product.min_stock_level is not None
        and product.stock_quantity <= (product.min_stock_level or 0)
    ]
    negative_margin = next(
        (
            product
            for product in products
            if product.cost is not None and product.price <= product.cost
        ),
        None,
    )
    top_product = product_sales[0] if product_sales else None
    slow_mover = next((item for item in product_sales if item["quantity"] <= 1), None)

    quick_wins: list[AIQuickWin] = []
    if low_stock:
        quick_wins.append(
            AIQuickWin(
                title=f"Reapprovisionner {low_stock[0].name}",
                detail=f"Stock {low_stock[0].stock_quantity}/{low_stock[0].min_stock_level or 0}",
                impact="Eviter une rupture",
            )
        )
    if negative_margin:
        quick_wins.append(
            AIQuickWin(
                title=f"Revoir le prix de {negative_margin.name}",
                detail=f"Prix {negative_margin.price} vs cout {negative_margin.cost}",
                impact="Marge negative",
            )
        )
    if top_product:
        quick_wins.append(
            AIQuickWin(
                title=f"Mettre en avant {top_product['name']}",
                detail=f"Top ventes (qte {top_product['quantity']})",
                impact="Augmenter le chiffre",
            )
        )
    if slow_mover:
        quick_wins.append(
            AIQuickWin(
                title=f"Promouvoir {slow_mover['name']}",
                detail=f"Ventes faibles (qte {slow_mover['quantity']})",
                impact="Ameliorer la rotation",
            )
        )

    total_recent = sum(float(sale.total_amount or 0) for sale in recent_sales)
    avg_sale = total_recent / len(recent_sales) if recent_sales else 0
    gross_profit = 0.0
    for sale in recent_sales:
        for item in sale.items or []:
            product = item.product or product_map.get(item.product_id)
            if not product or product.cost is None:
                continue
            revenue = float(item.total_price or 0)
            cost = float(product.cost or 0) * float(item.quantity or 0)
            gross_profit += revenue - cost
    margin_rate = (gross_profit / total_recent * 100) if total_recent > 0 else 0

    performance = AIRecommendationsPerformance(
        avg_sale=int(round(avg_sale)),
        margin_rate=int(round(margin_rate)),
        low_stock_count=len(low_stock),
    )

    return AIRecommendationsResponse(
        quick_wins=quick_wins[:4],
        performance=performance,
    )


@router.post("/chat", response_model=AIChatResponse)
def chat(
    payload: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.insights.read",))),
):
    now = datetime.now(timezone.utc)
    products = db.query(Product).all()
    product_map = {product.id: product for product in products}
    recent_sales = _load_sales_window(db, now - timedelta(days=7))
    product_sales = _aggregate_product_sales(recent_sales, product_map)
    product_sales.sort(key=lambda item: item["quantity"], reverse=True)

    low_stock = [
        product
        for product in products
        if product.min_stock_level is not None
        and product.stock_quantity <= (product.min_stock_level or 0)
    ]

    summary = {
        "total_recent": int(round(sum(float(sale.total_amount or 0) for sale in recent_sales))),
        "top_products": product_sales[:3],
        "low_stock": low_stock[:3],
    }
    suggestions = _build_chat_suggestions(summary)

    message = payload.message.lower()
    if "stock" in message or "inventaire" in message:
        if not summary["low_stock"]:
            response = "Aucun produit en stock critique actuellement."
        else:
            items = ", ".join(
                f"{product.name} ({product.stock_quantity})" for product in summary["low_stock"]
            )
            response = f"Produits en alerte: {items}."
    elif "vente" in message:
        response = f"Ventes des 7 derniers jours: {summary['total_recent']} HTG."
    elif "produit" in message:
        if not summary["top_products"]:
            response = "Aucune vente recente pour identifier les produits les plus vendus."
        else:
            items = ", ".join(
                f"{item['name']} ({item['quantity']})" for item in summary["top_products"]
            )
            response = f"Top produits recents: {items}."
    else:
        response = "Je peux vous aider avec vos ventes et votre stock. Essayez: \"ventes\", \"stock\" ou \"produits\"."

    return AIChatResponse(response=response, suggestions=suggestions)


@router.get("/chat/suggestions", response_model=AIChatSuggestions)
def chat_suggestions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "manager", allow_perms=("reports.insights.read",))),
):
    now = datetime.now(timezone.utc)
    products = db.query(Product).all()
    product_map = {product.id: product for product in products}
    recent_sales = _load_sales_window(db, now - timedelta(days=7))
    product_sales = _aggregate_product_sales(recent_sales, product_map)
    product_sales.sort(key=lambda item: item["quantity"], reverse=True)
    low_stock = [
        product
        for product in products
        if product.min_stock_level is not None
        and product.stock_quantity <= (product.min_stock_level or 0)
    ]
    summary = {
        "total_recent": int(round(sum(float(sale.total_amount or 0) for sale in recent_sales))),
        "top_products": product_sales[:3],
        "low_stock": low_stock[:3],
    }
    return AIChatSuggestions(suggestions=_build_chat_suggestions(summary))
