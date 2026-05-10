"""
routers/inventory.py
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from datetime import datetime, timezone
from models.schemas import CreateProductRequest, UpdateStockRequest, UserRole
from firebase_admin_init import branch_col
from services.rbac import require_min_role, same_branch_or_admin
import uuid

router = APIRouter()


@router.get("/")
async def list_products(request: Request, branch_id: str | None = None):
    tenant_id     = request.state.tenant_id
    target_branch = branch_id or request.state.branch_id
    same_branch_or_admin(request, target_branch)
    docs     = branch_col(tenant_id, target_branch, "products").stream()
    products = [{"product_id": d.id, **d.to_dict()} for d in docs]
    return {"products": products, "count": len(products)}


@router.post("/")
async def create_product(
    body: CreateProductRequest,
    request: Request,
    _=Depends(require_min_role(UserRole.BRANCH_MANAGER)),
):
    tenant_id = request.state.tenant_id
    branch_id = request.state.branch_id
    product_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    data = {
        **body.dict(),
        "product_id":  product_id,
        "tenant_id":   tenant_id,
        "branch_id":   branch_id,
        "created_at":  now,
        "updated_at":  now,
        "created_by":  request.state.uid,
    }
    branch_col(tenant_id, branch_id, "products").document(product_id).set(data)
    return {"message": "Product created", "product_id": product_id}


@router.patch("/stock")
async def adjust_stock(
    body: UpdateStockRequest,
    request: Request,
    _=Depends(require_min_role(UserRole.SUPERVISOR)),
):
    tenant_id = request.state.tenant_id
    branch_id = request.state.branch_id
    ref       = branch_col(tenant_id, branch_id, "products").document(body.product_id)
    doc       = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Product not found")
    current = doc.to_dict().get("stock", 0)
    new_stock = current + body.quantity_delta
    if new_stock < 0:
        raise HTTPException(status_code=400, detail=f"Stock cannot be negative. Current: {current}")
    ref.update({
        "stock":            new_stock,
        "last_adjusted_at": datetime.now(timezone.utc),
        "last_adjusted_by": request.state.uid,
        "adjustment_reason": body.reason,
    })
    return {"message": "Stock updated", "product_id": body.product_id, "new_stock": new_stock}