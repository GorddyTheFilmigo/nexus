"""routers/reports.py"""
from fastapi import APIRouter, Request, Depends
from models.schemas import UserRole
from firebase_admin_init import branch_col, col
from services.rbac import require_min_role

router = APIRouter()


@router.get("/summary")
async def summary(
    request: Request,
    branch_id: str | None = None,
    start_date: str = "",
    end_date: str = "",
    _=Depends(require_min_role(UserRole.SUPERVISOR)),
):
    """Revenue summary. Super admin sees all branches; others see own branch."""
    tenant_id   = request.state.tenant_id
    role        = UserRole(request.state.role)
    target      = branch_id if role == UserRole.SUPER_ADMIN and branch_id else request.state.branch_id

    query = branch_col(tenant_id, target, "orders").where("status", "==", "completed")
    docs  = list(query.stream())

    total_revenue = sum(d.to_dict().get("total", 0) for d in docs)
    total_orders  = len(docs)
    avg_ticket    = round(total_revenue / total_orders, 2) if total_orders else 0

    payment_breakdown = {}
    for d in docs:
        pm = d.to_dict().get("payment_method", "cash")
        payment_breakdown[pm] = payment_breakdown.get(pm, 0) + d.to_dict().get("total", 0)

    return {
        "total_revenue":    total_revenue,
        "total_orders":     total_orders,
        "avg_ticket":       avg_ticket,
        "sales_by_payment": payment_breakdown,
    }


@router.get("/branches")
async def branch_overview(
    request: Request,
    _=Depends(require_min_role(UserRole.SUPER_ADMIN)),
):
    """Cross-branch report — super admin only."""
    tenant_id = request.state.tenant_id
    orders = list(col("orders").where("tenant_id", "==", tenant_id).stream())
    branch_map = {}
    for d in orders:
        data = d.to_dict()
        bid  = data.get("branch_id", "unknown")
        if bid not in branch_map:
            branch_map[bid] = {"revenue": 0, "orders": 0}
        if data.get("status") == "completed":
            branch_map[bid]["revenue"] += data.get("total", 0)
            branch_map[bid]["orders"]  += 1
    return {"branches": branch_map}