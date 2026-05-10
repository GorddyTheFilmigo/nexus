"""
routers/users.py — User management
Only SUPER_ADMIN and BRANCH_MANAGER can manage users.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from datetime import datetime, timezone
from models.schemas import CreateUserRequest, UpdateUserRequest, UserRole
from firebase_admin_init import get_auth, col
from services.rbac import require_min_role

router = APIRouter()


@router.get("/")
async def list_users(
    request: Request,
    branch_id: str | None = None,
    _=Depends(require_min_role(UserRole.BRANCH_MANAGER)),
):
    """
    List all users.
    - SUPER_ADMIN: sees all users (optionally filtered by branch)
    - BRANCH_MANAGER: sees only users in their branch
    """
    role = UserRole(request.state.role)
    db_col = col("users")

    if role == UserRole.SUPER_ADMIN:
        query = db_col.where("tenant_id", "==", request.state.tenant_id)
        if branch_id:
            query = query.where("branch_id", "==", branch_id)
    else:
        query = db_col.where("branch_id", "==", request.state.branch_id)

    docs = query.stream()
    users = []
    for d in docs:
        data = d.to_dict()
        data.pop("password_hash", None)
        users.append({"uid": d.id, **data})

    return {"users": users, "count": len(users)}


@router.post("/")
async def create_user(
    body: CreateUserRequest,
    request: Request,
    _=Depends(require_min_role(UserRole.BRANCH_MANAGER)),
):
    """Create a new Firebase Auth user and Firestore profile."""
    fb_auth = get_auth()
    tenant_id = request.state.tenant_id
    creator_role = UserRole(request.state.role)

    # Branch managers can only create cashiers/supervisors
    if creator_role == UserRole.BRANCH_MANAGER and body.role in [
        UserRole.BRANCH_MANAGER, UserRole.SUPER_ADMIN
    ]:
        raise HTTPException(
            status_code=403,
            detail="Branch managers can only create Cashier or Supervisor accounts",
        )

    # Check email uniqueness
    try:
        fb_auth.get_user_by_email(body.email)
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    except fb_auth.UserNotFoundError:
        pass

    # Create Firebase Auth user
    try:
        fb_user = fb_auth.create_user(
            email=body.email,
            password=body.password,
            display_name=body.name,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create auth user: {str(e)}")

    # Set custom claims
    fb_auth.set_custom_user_claims(fb_user.uid, {
        "role":      body.role.value,
        "tenant_id": tenant_id,
        "branch_id": body.branch_id,
    })

    # Create Firestore profile
    now = datetime.now(timezone.utc)
    profile = {
        "name":              body.name,
        "email":             body.email,
        "role":              body.role.value,
        "branch_id":         body.branch_id,
        "tenant_id":         tenant_id,
        "status":            "active",
        "created_by":        request.state.uid,
        "created_at":        now,
        "last_login":        None,
        "active_session_id": None,
    }
    col("users").document(fb_user.uid).set(profile)

    return {
        "message": "User created successfully",
        "uid": fb_user.uid,
        "email": body.email,
        "role": body.role.value,
    }


@router.put("/{uid}")
async def update_user(
    uid: str,
    body: UpdateUserRequest,
    request: Request,
    _=Depends(require_min_role(UserRole.BRANCH_MANAGER)),
):
    """Update user profile and role."""
    updates = body.dict(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = datetime.now(timezone.utc)
    updates["updated_by"] = request.state.uid

    col("users").document(uid).update(updates)

    # Sync custom claims if role or branch changed
    if "role" in updates or "branch_id" in updates:
        user_doc = col("users").document(uid).get().to_dict()
        get_auth().set_custom_user_claims(uid, {
            "role":      user_doc.get("role"),
            "tenant_id": user_doc.get("tenant_id"),
            "branch_id": user_doc.get("branch_id"),
        })

    return {"message": "User updated", "uid": uid}


@router.patch("/{uid}/status")
async def toggle_user_status(
    uid: str,
    action: str,   # "activate" or "deactivate"
    request: Request,
    _=Depends(require_min_role(UserRole.BRANCH_MANAGER)),
):
    """Activate or deactivate a user account."""
    if action not in ["activate", "deactivate"]:
        raise HTTPException(status_code=400, detail="action must be 'activate' or 'deactivate'")

    new_status = "active" if action == "activate" else "inactive"

    # Disable/enable Firebase Auth account
    get_auth().update_user(uid, disabled=(new_status == "inactive"))

    col("users").document(uid).update({
        "status":          new_status,
        "status_changed_at": datetime.now(timezone.utc),
        "status_changed_by": request.state.uid,
    })

    return {"message": f"User {new_status}", "uid": uid, "status": new_status}


@router.delete("/{uid}")
async def delete_user(
    uid: str,
    request: Request,
    _=Depends(require_min_role(UserRole.SUPER_ADMIN)),
):
    """Permanently delete user (super admin only). Prefer deactivation."""
    get_auth().delete_user(uid)
    col("users").document(uid).delete()
    return {"message": "User permanently deleted", "uid": uid}