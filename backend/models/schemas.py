"""
models/schemas.py — Pydantic request/response models
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


# ─── ENUMS ───────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CASHIER         = "cashier"
    SUPERVISOR      = "supervisor"
    BRANCH_MANAGER  = "branch_manager"
    SUPER_ADMIN     = "super_admin"

class PaymentMethod(str, Enum):
    CASH  = "cash"
    MPESA = "mpesa"
    CARD  = "card"

class OrderStatus(str, Enum):
    COMPLETED = "completed"
    REFUNDED  = "refunded"
    VOIDED    = "voided"


# ─── AUTH ────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    id_token:     str
    tenant_id:    str
    company_name: str
    country:      str = "KE"
    currency:     str = "KES"
    tax_rate:     float = 0.16
    tax_pin:      Optional[str] = None
    phone:        Optional[str] = None
    plan:         str = "growth"
    admin_name:   str
    branches:     List[str]

class RegisterResponse(BaseModel):
    message:   str
    tenant_id: str
    uid:       str
    branches:  List[str]

class LoginRequest(BaseModel):
    id_token:  str = Field(..., description="Firebase ID token from frontend sign-in")
    branch_id: str

class LoginResponse(BaseModel):
    access_token: str
    user_id:      str
    name:         str
    role:         UserRole
    branch_id:    str
    branch_name:  str
    tenant_id:    str
    permissions:  List[str]

class TokenPayload(BaseModel):
    uid:       str
    tenant_id: str
    branch_id: str
    role:      UserRole
    email:     str


# ─── USER ────────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    name:      str
    email:     EmailStr
    role:      UserRole
    branch_id: str
    password:  str = Field(..., min_length=8)

class UpdateUserRequest(BaseModel):
    name:      Optional[str] = None
    role:      Optional[UserRole] = None
    branch_id: Optional[str] = None

class UserResponse(BaseModel):
    uid:        str
    name:       str
    email:      str
    role:       UserRole
    branch_id:  str
    branch_name: str
    status:     Literal["active", "inactive"]
    created_at: datetime
    last_login: Optional[datetime] = None


# ─── SALES ───────────────────────────────────────────────────────────────────

class CartItem(BaseModel):
    product_id: str
    name:       str
    qty:        int = Field(..., gt=0)
    unit_price: float

class CreateSaleRequest(BaseModel):
    items:          List[CartItem]
    payment_method: PaymentMethod
    discount:       float = 0.0
    customer_name:  Optional[str] = None
    customer_phone: Optional[str] = None
    notes:          Optional[str] = None

class SaleResponse(BaseModel):
    order_id:       str
    tenant_id:      str
    branch_id:      str
    cashier_id:     str
    cashier_name:   str
    items:          List[CartItem]
    subtotal:       float
    tax:            float
    discount:       float
    total:          float
    payment_method: PaymentMethod
    status:         OrderStatus
    created_at:     datetime
    receipt_url:    Optional[str] = None

class RefundRequest(BaseModel):
    order_id: str
    reason:   str
    items:    Optional[List[str]] = None


# ─── INVENTORY ───────────────────────────────────────────────────────────────

class CreateProductRequest(BaseModel):
    name:                str
    category:            str
    price:               float = Field(..., gt=0)
    stock:               int = Field(..., ge=0)
    sku:                 Optional[str] = None
    barcode:             Optional[str] = None
    low_stock_threshold: int = 10
    unit:                str = "piece"

class UpdateStockRequest(BaseModel):
    product_id:     str
    quantity_delta: int
    reason:         str


# ─── SESSION ─────────────────────────────────────────────────────────────────

class SessionResponse(BaseModel):
    session_id:       str
    user_id:          str
    user_name:        str
    branch_id:        str
    branch_name:      str
    login_at:         datetime
    logout_at:        Optional[datetime] = None
    duration_seconds: Optional[int] = None
    sales_count:      int
    sales_total:      float
    is_active:        bool


# ─── REPORTS ─────────────────────────────────────────────────────────────────

class DateRangeQuery(BaseModel):
    start_date: str
    end_date:   str
    branch_id:  Optional[str] = None

class ReportSummary(BaseModel):
    total_revenue:    float
    total_orders:     int
    avg_ticket:       float
    top_products:     List[dict]
    sales_by_day:     List[dict]
    sales_by_payment: dict
    branch_breakdown: Optional[List[dict]] = None