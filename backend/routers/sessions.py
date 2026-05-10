"""routers/sessions.py — User session tracking"""
from fastapi import APIRouter, Request, Depends, HTTPException
from models.schemas import UserRole
from firebase_admin_init import col
from services.rbac import require_min_role

router = APIRouter()


@router.get("/")
async def list_sessions(
    request: Request,
    user_id: str | None = None,
    branch_id: str | None = None,
    active_only: bool = False,
    limit: int = 100,
    _=Depends(require_min_role(UserRole.SUPERVISOR)),
):
    role      = UserRole(request.state.role)
    query     = col("sessions")

    if role != UserRole.SUPER_ADMIN:
        query = query.where("branch_id", "==", request.state.branch_id)
    elif branch_id:
        query = query.where("branch_id", "==", branch_id)

    if user_id:
        query = query.where("uid", "==", user_id)

    if active_only:
        query = query.where("is_active", "==", True)

    docs = list(query.order_by("login_at", direction="DESCENDING").limit(limit).stream())
    sessions = [{"session_id": d.id, **d.to_dict()} for d in docs]
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/active")
async def active_sessions(
    request: Request,
    _=Depends(require_min_role(UserRole.SUPERVISOR)),
):
    """Return all currently active sessions."""
    role  = UserRole(request.state.role)
    query = col("sessions").where("is_active", "==", True)
    if role != UserRole.SUPER_ADMIN:
        query = query.where("branch_id", "==", request.state.branch_id)
    docs  = list(query.stream())
    return {"active_sessions": [d.to_dict() for d in docs], "count": len(docs)}


@router.post("/{session_id}/force-logout")
async def force_logout(
    session_id: str,
    request: Request,
    _=Depends(require_min_role(UserRole.SUPER_ADMIN)),
):
    """Force terminate a session — super admin only."""
    from datetime import datetime, timezone
    ref = col("sessions").document(session_id)
    doc = ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Session not found")

    data     = doc.to_dict()
    login_at = data.get("login_at")
    now      = datetime.now(timezone.utc)
    duration = int((now - login_at).total_seconds()) if login_at else 0

    ref.update({
        "is_active":         False,
        "logout_at":         now,
        "duration_seconds":  duration,
        "force_logout_by":   request.state.uid,
    })

    # Revoke Firebase tokens for that user
    try:
        from firebase_admin_init import get_auth
        get_auth().revoke_refresh_tokens(data.get("uid"))
    except Exception:
        pass

    return {"message": "Session terminated", "session_id": session_id}