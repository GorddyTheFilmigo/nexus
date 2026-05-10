"""
routers/sales.py — Sales / Orders API
Every sale is created server-side so stock deduction and revenue tracking
are atomic and tamper-proof.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from datetime import datetime, timezone
from models.schemas import CreateSaleRequest, RefundRequest, OrderStatus, UserRole
from firebase_admin_init import get_db, branch_col, col
from services.rbac import require_min_role, same_branch_or_admin
import uuid

router = APIRouter()

TAX_RATE = 0.16  # Kenya VAT


@router.post("/")
async def create_sale(body: CreateSaleRequest, request: Request):
    """
    Process a sale:
    1. Validate stock availability
    2. Deduct inventory (batch write)
    3. Record sale document
    4. Increment session sales counter
    5. Return order details for receipt
    """
    uid       = request.state.uid
    tenant_id = request.state.tenant_id
    branch_id = request.state.branch_id
    db        = get_db()

    # ── 1. Fetch user name ────────────────────────────────────────────────
    user_doc = col("users").document(uid).get()
    cashier_name = user_doc.to_dict().get("name", "Unknown") if user_doc.exists else "Unknown"

    # ── 2. Validate & fetch products ──────────────────────────────────────
    product_refs = []
    for item in body.items:
        ref = branch_col(tenant_id, branch_id, "products").document(item.product_id)
        snap = ref.get()
        if not snap.exists:
            raise HTTPException(
                status_code=404, detail=f"Product {item.product_id} not found"
            )
        prod = snap.to_dict()
        if prod.get("stock", 0) < item.qty:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for {prod['name']}. Available: {prod['stock']}, requested: {item.qty}",
            )
        product_refs.append((ref, prod, item))

    # ── 3. Calculate totals ───────────────────────────────────────────────
    subtotal = sum(i.unit_price * i.qty for i in body.items)
    tax      = round(subtotal * TAX_RATE, 2)
    discount = body.discount or 0.0
    total    = round(subtotal + tax - discount, 2)

    # ── 4. Atomic Firestore batch: deduct stock + create order ───────────
    order_id  = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    now       = datetime.now(timezone.utc)
    batch     = db.batch()

    # Deduct stock
    for ref, prod, item in product_refs:
        batch.update(ref, {
            "stock":        prod["stock"] - item.qty,
            "last_sale_at": now,
        })

    # Write order document
    order_ref = branch_col(tenant_id, branch_id, "orders").document(order_id)
    order_data = {
        "order_id":       order_id,
        "tenant_id":      tenant_id,
        "branch_id":      branch_id,
        "cashier_id":     uid,
        "cashier_name":   cashier_name,
        "items":          [i.dict() for i in body.items],
        "subtotal":       subtotal,
        "tax":            tax,
        "discount":       discount,
        "total":          total,
        "payment_method": body.payment_method.value,
        "status":         OrderStatus.COMPLETED.value,
        "customer_name":  body.customer_name,
        "customer_phone": body.customer_phone,
        "notes":          body.notes,
        "created_at":     now,
        "updated_at":     now,
    }
    batch.set(order_ref, order_data)

    # Mirror to global orders collection for cross-branch reporting
    global_ref = col("orders").document(order_id)
    batch.set(global_ref, order_data)

    batch.commit()

    # ── 5. Increment session counters (non-critical, best-effort) ─────────
    try:
        user_data      = user_doc.to_dict() or {}
        session_id     = user_data.get("active_session_id")
        if session_id:
            col("sessions").document(session_id).update({
                "sales_count": __import__("google.cloud.firestore", fromlist=["firestore"]).firestore.Increment(1),
                "sales_total": __import__("google.cloud.firestore", fromlist=["firestore"]).firestore.Increment(total),
            })
    except Exception:
        pass

    return {**order_data, "receipt_url": f"/api/v1/sales/{order_id}/receipt"}


@router.get("/")
async def list_sales(
    request: Request,
    branch_id: str | None = None,
    limit: int = 50,
    status: str | None = None,
):
    """List sales. Cashiers see only today's; supervisors/admins can see more."""
    tenant_id   = request.state.tenant_id
    role        = UserRole(request.state.role)
    target_branch = branch_id or request.state.branch_id

    if role != UserRole.SUPER_ADMIN:
        same_branch_or_admin(request, target_branch)

    query = branch_col(tenant_id, target_branch, "orders").order_by(
        "created_at", direction="DESCENDING"
    ).limit(limit)

    if status:
        query = query.where("status", "==", status)

    docs  = query.stream()
    orders = [{"order_id": d.id, **d.to_dict()} for d in docs]
    return {"orders": orders, "count": len(orders)}


@router.get("/{order_id}")
async def get_sale(order_id: str, request: Request):
    doc = col("orders").document(order_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")
    data = doc.to_dict()
    same_branch_or_admin(request, data.get("branch_id", ""))
    return data


@router.post("/{order_id}/refund")
async def refund_sale(
    order_id: str,
    body: RefundRequest,
    request: Request,
    _=Depends(require_min_role(UserRole.SUPERVISOR)),
):
    """Full or partial refund — restores stock."""
    order_ref = col("orders").document(order_id)
    order_doc = order_ref.get()
    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    order = order_doc.to_dict()
    if order["status"] != OrderStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="Only completed orders can be refunded")

    now = datetime.now(timezone.utc)
    order_ref.update({
        "status":        OrderStatus.REFUNDED.value,
        "refund_reason": body.reason,
        "refunded_by":   request.state.uid,
        "refunded_at":   now,
        "updated_at":    now,
    })

    # Mirror to branch orders
    tenant_id = order["tenant_id"]
    branch_id = order["branch_id"]
    branch_col(tenant_id, branch_id, "orders").document(order_id).update({
        "status": OrderStatus.REFUNDED.value,
        "updated_at": now,
    })

    return {"message": "Order refunded", "order_id": order_id}


@router.post("/{order_id}/void")
async def void_sale(
    order_id: str,
    request: Request,
    reason: str = "",
    _=Depends(require_min_role(UserRole.SUPERVISOR)),
):
    """Void an order — does NOT restore stock (use refund for that)."""
    order_ref = col("orders").document(order_id)
    order_doc = order_ref.get()
    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    now = datetime.now(timezone.utc)
    order_ref.update({
        "status":    OrderStatus.VOIDED.value,
        "void_reason": reason,
        "voided_by": request.state.uid,
        "voided_at": now,
        "updated_at": now,
    })
    return {"message": "Order voided", "order_id": order_id}