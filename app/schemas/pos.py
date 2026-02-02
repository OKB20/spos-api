from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Token(ORMModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(ORMModel):
    sub: UUID
    exp: datetime
    type: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserBase(ORMModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    store_name: Optional[str] = None
    disabled: bool = False
    permissions: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = "employee"
    store_name: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    store_name: Optional[str] = None
    permissions: Optional[dict[str, Any]] = None
    disabled: Optional[bool] = None


class UserPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=72)


class UserSelfUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    store_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class CustomerBase(ORMModel):
    id: UUID
    name: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    customer_type: Optional[str] = None
    discount_percentage: Optional[float] = None
    total_purchases: Optional[float] = None
    loyalty_points: Optional[int] = 0
    is_active: Optional[bool] = None
    last_purchase_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    customer_type: Optional[str] = None
    discount_percentage: Optional[float] = None
    loyalty_points: Optional[int] = 0
    is_active: bool = True


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    customer_type: Optional[str] = None
    discount_percentage: Optional[float] = None
    is_active: Optional[bool] = None
    total_purchases: Optional[float] = None
    loyalty_points: Optional[int] = None
    last_purchase_date: Optional[datetime] = None


class ProductBase(ORMModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: float
    cost: Optional[float] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    stock_quantity: int
    min_stock_level: Optional[int] = None
    unit: Optional[str] = None
    is_active: Optional[bool] = None
    expiration_date: Optional[date] = None
    stock_alert_sent: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProductCreate(BaseModel):
    name: str
    price: float
    cost: Optional[float] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    stock_quantity: int = 0
    min_stock_level: Optional[int] = None
    unit: Optional[str] = None
    is_active: bool = True
    expiration_date: Optional[date] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    cost: Optional[float] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    category: Optional[str] = None
    stock_quantity: Optional[int] = None
    min_stock_level: Optional[int] = None
    unit: Optional[str] = None
    is_active: Optional[bool] = None
    expiration_date: Optional[date] = None
    stock_alert_sent: Optional[bool] = None


class SaleItemBase(ORMModel):
    id: UUID
    product_id: UUID
    quantity: int
    unit_price: float
    discount_amount: Optional[float] = None
    total_price: float


class SaleItemCreate(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: float
    discount_amount: Optional[float] = None
    total_price: float


class SaleItemRead(SaleItemBase):
    product: Optional[ProductBase] = None


class SaleBase(ORMModel):
    id: UUID
    sale_number: str
    idempotency_key: Optional[str] = None
    cashier_id: UUID
    customer_id: Optional[UUID] = None
    subtotal: float
    tax_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    total_amount: float
    payment_method: str
    payment_status: Optional[str] = None
    notes: Optional[str] = None
    sale_date: datetime
    created_at: Optional[datetime] = None


class SaleCreate(BaseModel):
    idempotency_key: Optional[str] = None
    customer_id: Optional[UUID] = None
    subtotal: float
    tax_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    total_amount: float
    payment_method: str
    payment_status: Optional[str] = None
    points_redeemed: Optional[int] = 0
    notes: Optional[str] = None
    items: List[SaleItemCreate]


class SaleRead(SaleBase):
    customer: Optional[CustomerBase] = None
    items: List[SaleItemRead] = []


class ReturnBase(ORMModel):
    id: UUID
    sale_id: UUID
    product_id: UUID
    processed_by: UUID
    quantity: int
    reason: str
    refund_amount: float
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class ReturnCreate(BaseModel):
    sale_id: UUID
    product_id: UUID
    processed_by: UUID
    quantity: int
    reason: str
    refund_amount: float
    status: Optional[str] = None


class ReturnUpdate(BaseModel):
    status: Optional[str] = None


class PurchaseItemBase(ORMModel):
    id: UUID
    purchase_id: UUID
    product_id: UUID
    quantity: int
    unit_price: float
    total_price: float


class PurchaseItemCreate(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: float
    total_price: float


class PurchaseBase(ORMModel):
    id: UUID
    supplier_name: str
    total_amount: float
    purchase_date: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PurchaseCreate(BaseModel):
    supplier_name: str
    total_amount: float
    purchase_date: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    items: List[PurchaseItemCreate]


class PurchaseUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[PurchaseItemCreate]] = None


class PurchaseRead(PurchaseBase):
    items: List[PurchaseItemBase] = []


class InventoryTransactionBase(ORMModel):
    id: UUID
    product_id: UUID
    quantity_change: int
    transaction_type: str
    reference_id: Optional[UUID] = None
    reference_type: Optional[str] = None
    created_by: UUID
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class InventoryTransactionCreate(BaseModel):
    product_id: UUID
    quantity_change: int
    transaction_type: str
    reference_id: Optional[UUID] = None
    reference_type: Optional[str] = None
    notes: Optional[str] = None


class InventoryCountBase(ORMModel):
    id: UUID
    product_id: Optional[UUID] = None
    physical_count: int
    system_count: int
    difference: Optional[int] = None
    status: str
    count_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class InventoryCountCreate(BaseModel):
    product_id: Optional[UUID] = None
    physical_count: int
    system_count: int
    difference: Optional[int] = None
    status: str
    count_date: Optional[datetime] = None


class InventoryCountUpdate(BaseModel):
    physical_count: Optional[int] = None
    system_count: Optional[int] = None
    difference: Optional[int] = None
    status: Optional[str] = None
    count_date: Optional[datetime] = None


class PromotionBase(ORMModel):
    id: UUID
    name: str
    type: str
    value: float
    start_date: datetime
    end_date: datetime
    current_uses: Optional[int] = None
    max_uses: Optional[int] = None
    min_purchase_amount: Optional[float] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None


class PromotionCreate(BaseModel):
    name: str
    type: str
    value: float
    start_date: datetime
    end_date: datetime
    max_uses: Optional[int] = None
    min_purchase_amount: Optional[float] = None
    is_active: bool = True


class PromotionUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    value: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    current_uses: Optional[int] = None
    max_uses: Optional[int] = None
    min_purchase_amount: Optional[float] = None
    is_active: Optional[bool] = None


class AuditLogBase(ORMModel):
    id: UUID
    user_id: UUID
    action: str
    table_name: str
    record_id: Optional[UUID] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    created_at: Optional[datetime] = None


class AuditLogCreate(BaseModel):
    user_id: UUID
    action: str
    table_name: str
    record_id: Optional[UUID] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None


class SystemSettingBase(ORMModel):
    id: UUID
    setting_key: str
    setting_value: dict
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SystemSettingCreate(BaseModel):
    setting_key: str
    setting_value: dict
    description: Optional[str] = None


class SystemSettingUpdate(BaseModel):
    setting_value: Optional[dict] = None
    description: Optional[str] = None


class ExpirationAlertBase(ORMModel):
    id: UUID
    product_id: UUID
    alert_date: date
    alert_sent: Optional[bool] = None
    days_until_expiration: int
    created_at: Optional[datetime] = None


class ReportSummary(ORMModel):
    total_sales_amount: float
    total_sales_count: int
    total_products: int
    total_inventory_value: float


class AIInsightsResponse(BaseModel):
    opportunities: List[str]
    attention_points: List[str]
    generated_at: datetime


class AIAnalyticsMonthlyPoint(BaseModel):
    month: str
    actual: int
    predicted: int


class AIAnalyticsCustomerSegment(BaseModel):
    name: str
    value: int


class AIAnalyticsProductPerformance(BaseModel):
    product: str
    performance: int
    trend: str


class AIAnalyticsMetrics(BaseModel):
    total_recent: int
    avg_sale: int
    gross_profit: int
    low_stock_count: int


class AIAnalyticsResponse(BaseModel):
    monthly_series: List[AIAnalyticsMonthlyPoint]
    customer_segments: List[AIAnalyticsCustomerSegment]
    product_performance: List[AIAnalyticsProductPerformance]
    metrics: AIAnalyticsMetrics


class AISalesPrediction(BaseModel):
    period: str
    prediction: str
    confidence: int
    trend: str
    change: str
    factors: List[str]


class AIStockPrediction(BaseModel):
    product: str
    current_stock: int
    predicted_demand: int
    days_remaining: int
    urgency: str
    recommendation: str


class AIMarketTrend(BaseModel):
    trend: str
    impact: str
    probability: int
    timeframe: str
    action: str


class AIPredictionsResponse(BaseModel):
    sales_predictions: List[AISalesPrediction]
    stock_predictions: List[AIStockPrediction]
    market_trends: List[AIMarketTrend]


class AIQuickWin(BaseModel):
    title: str
    detail: str
    impact: str


class AIRecommendationsPerformance(BaseModel):
    avg_sale: int
    margin_rate: int
    low_stock_count: int


class AIRecommendationsResponse(BaseModel):
    quick_wins: List[AIQuickWin]
    performance: AIRecommendationsPerformance


class AIChatRequest(BaseModel):
    message: str


class AIChatResponse(BaseModel):
    response: str
    suggestions: List[str]


class AIChatSuggestions(BaseModel):
    suggestions: List[str]
