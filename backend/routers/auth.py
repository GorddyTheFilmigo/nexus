"""
routers/auth.py — Authentication & Registration endpoints
"""

from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
from models.schemas import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, UserRole
from firebase_admin_init import get_auth, get_db, tenant_col, col
from services.rbac import get_permissions
import uuid

router = APIRouter()


# ─── REGISTER ────────────────────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest):
    """
    Called after Firebase Client SDK creates the Auth user.
    Creates: tenant doc, branch docs, super admin user profile, tenant settings.
    """
    fb_auth = get_auth()
    db      = get_db()

    # 1. Verify the Firebase ID token
    # check_revoked=False is required for tokens issued via Firebase REST API
    try:
        decoded = fb_auth.verify_id_token(body.id_token, check_revoked=False)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

    uid        = decoded["uid"]
    tenant_id  = body.tenant_id

    # 2. Check tenant doesn't already exist
    tenant_ref = db.collection("tenants").document(tenant_id)
    if tenant_ref.get().exists:
        raise HTTPException(status_code=409, detail="A company with this ID already exists")

    now = datetime.now(timezone.utc)

    # 3. Create tenant document
    tenant_ref.set({
        "tenant_id":   tenant_id,
        "name":        body.company_name,
        "plan":        body.plan,
        "country":     body.country,
        "currency":    body.currency,
        "tax_rate":    body.tax_rate,
        "tax_pin":     body.tax_pin or "",
        "phone":       body.phone or "",
        "timezone":    "Africa/Nairobi",
        "created_at":  now,
        "is_active":   True,
        "owner_uid":   uid,
    })

    # 4. Create tenant settings
    tenant_ref.collection("settings").document("general").set({
        "receipt_header": body.company_name.upper(),
        "receipt_footer": "Thank you for shopping with us!",
        "tax_pin":        body.tax_pin or "",
        "logo_url":       None,
        "printer_type":   "thermal_80mm",
    })

    # 5. Create branches
    branch_ids   = []
    first_branch = None
    for idx, branch_name in enumerate(body.branches):
        branch_id = "branch-" + branch_name.lower().replace(" ", "-").replace("/", "-") + "-" + uid[:4]
        tenant_ref.collection("branches").document(branch_id).set({
            "branch_id":  branch_id,
            "name":       branch_name,
            "address":    "",
            "phone":      body.phone or "",
            "manager_id": uid,
            "is_active":  True,
            "created_at": now,
        })
        branch_ids.append(branch_id)
        if idx == 0:
            first_branch = branch_id

    # 6. Create super admin Firestore profile
    col("users").document(uid).set({
        "name":              body.admin_name,
        "email":             decoded.get("email", ""),
        "role":              "super_admin",
        "branch_id":         first_branch,
        "tenant_id":         tenant_id,
        "status":            "active",
        "created_at":        now,
        "created_by":        uid,
        "last_login":        None,
        "active_session_id": None,
    })

    # 7. Set custom claims on Firebase Auth user
    fb_auth.set_custom_user_claims(uid, {
        "role":      "super_admin",
        "tenant_id": tenant_id,
        "branch_id": first_branch,
    })

    return RegisterResponse(
        message="Company registered successfully",
        tenant_id=tenant_id,
        uid=uid,
        branches=branch_ids,
    )


# ─── LOGIN ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """
    Verify Firebase ID token, record session start, return enriched user data.
    """
    fb_auth = get_auth()

    try:
        decoded = fb_auth.verify_id_token(body.id_token, check_revoked=False)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

    uid = decoded["uid"]

    # Fetch user profile from Firestore
    try:
        user_ref = col("users").document(uid)
        user_doc = user_ref.get()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch user profile")

    if not user_doc.exists:
        raise HTTPException(
            status_code=404,
            detail="User profile not found. Please register your company first or contact your administrator."
        )

    user_data = user_doc.to_dict()

    if user_data.get("status") != "active":
        raise HTTPException(status_code=403, detail="Your account has been deactivated. Contact your administrator.")

    branch_id     = body.branch_id
    allowed_branch = user_data.get("branch_id")
    role          = UserRole(user_data.get("role", "cashier"))
    tenant_id     = user_data.get("tenant_id", "")

    # Super admin can log in from any branch
    if role != UserRole.SUPER_ADMIN and allowed_branch != branch_id:
        raise HTTPException(
            status_code=403,
            detail=f"You are not assigned to this branch. Your branch: {allowed_branch}"
        )

    # Fetch branch name
    try:
        branch_doc  = tenant_col(tenant_id, "branches").document(branch_id).get()
        branch_name = branch_doc.to_dict().get("name", branch_id) if branch_doc.exists else branch_id
    except Exception:
        branch_name = branch_id

    # Record session start
    session_ref = col("sessions").document()
    session_ref.set({
        "session_id":  session_ref.id,
        "uid":         uid,
        "user_name":   user_data.get("name", ""),
        "tenant_id":   tenant_id,
        "branch_id":   branch_id,
        "branch_name": branch_name,
        "role":        role.value,
        "login_at":    datetime.now(timezone.utc),
        "logout_at":   None,
        "is_active":   True,
        "sales_count": 0,
        "sales_total": 0.0,
        "ip":          "",
    })

    # Update last_login
    user_ref.update({
        "last_login":        datetime.now(timezone.utc),
        "active_session_id": session_ref.id,
    })

    # Refresh custom claims
    fb_auth.set_custom_user_claims(uid, {
        "role":      role.value,
        "tenant_id": tenant_id,
        "branch_id": branch_id,
    })

    return LoginResponse(
        access_token=body.id_token,
        user_id=uid,
        name=user_data.get("name", ""),
        role=role,
        branch_id=branch_id,
        branch_name=branch_name,
        tenant_id=tenant_id,
        permissions=get_permissions(role),
    )


# ─── LOGOUT ──────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(request: Request):
    """Record session end and duration."""
    uid = request.state.uid
    try:
        user_doc   = col("users").document(uid).get()
        user_data  = user_doc.to_dict() if user_doc.exists else {}
        session_id = user_data.get("active_session_id")

        if session_id:
            session_ref = col("sessions").document(session_id)
            session_doc = session_ref.get()
            if session_doc.exists:
                login_at  = session_doc.to_dict().get("login_at")
                logout_at = datetime.now(timezone.utc)
                duration  = int((logout_at - login_at).total_seconds()) if login_at else 0
                session_ref.update({
                    "logout_at":        logout_at,
                    "is_active":        False,
                    "duration_seconds": duration,
                })
        col("users").document(uid).update({"active_session_id": None})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Logout error: {str(e)}")

    return {"message": "Logged out successfully"}


# ─── ME ──────────────────────────────────────────────────────────────────────

@router.get("/me")
async def me(request: Request):
    """Return current user profile."""
    uid  = request.state.uid
    doc  = col("users").document(uid).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    data = doc.to_dict()
    data.pop("password_hash", None)
    return {"uid": uid, **data}