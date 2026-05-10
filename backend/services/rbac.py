"""
services/rbac.py — Role-Based Access Control
Use as FastAPI dependency: Depends(require_role([UserRole.SUPER_ADMIN]))
"""

from fastapi import HTTPException, Request, Depends
from models.schemas import UserRole
from typing import List

ROLE_HIERARCHY = {
    UserRole.CASHIER:        1,
    UserRole.SUPERVISOR:     2,
    UserRole.BRANCH_MANAGER: 3,
    UserRole.SUPER_ADMIN:    4,
}

# Permission map — what each role can do
PERMISSIONS = {
    UserRole.CASHIER: [
        "sales:create",
        "sales:read_own",
        "inventory:read",
        "sessions:read_own",
    ],
    UserRole.SUPERVISOR: [
        "sales:create",
        "sales:read",
        "sales:void",
        "inventory:read",
        "inventory:adjust_stock",
        "sessions:read",
        "reports:read_branch",
    ],
    UserRole.BRANCH_MANAGER: [
        "sales:create",
        "sales:read",
        "sales:void",
        "sales:refund",
        "inventory:read",
        "inventory:write",
        "inventory:adjust_stock",
        "users:read",
        "sessions:read",
        "reports:read_branch",
    ],
    UserRole.SUPER_ADMIN: [
        "sales:create",
        "sales:read",
        "sales:void",
        "sales:refund",
        "inventory:read",
        "inventory:write",
        "inventory:adjust_stock",
        "users:read",
        "users:write",
        "users:deactivate",
        "sessions:read",
        "sessions:force_logout",
        "reports:read_branch",
        "reports:read_global",
        "branches:write",
    ],
}


def require_role(allowed_roles: List[UserRole]):
    """FastAPI dependency — raises 403 if user role is insufficient."""
    def _check(request: Request):
        user_role = UserRole(getattr(request.state, "role", "cashier"))
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user_role}' is not authorised for this action. Required: {[r.value for r in allowed_roles]}",
            )
        return user_role
    return _check


def require_min_role(min_role: UserRole):
    """Accepts the given role OR any higher role."""
    def _check(request: Request):
        user_role = UserRole(getattr(request.state, "role", "cashier"))
        if ROLE_HIERARCHY.get(user_role, 0) < ROLE_HIERARCHY.get(min_role, 99):
            raise HTTPException(
                status_code=403,
                detail=f"Minimum role required: {min_role.value}",
            )
        return user_role
    return _check


def get_permissions(role: UserRole) -> List[str]:
    return PERMISSIONS.get(role, [])


def has_permission(role: UserRole, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, [])


def same_branch_or_admin(request: Request, branch_id: str):
    """Ensure user can only access their own branch data, unless super_admin."""
    role = UserRole(getattr(request.state, "role", "cashier"))
    user_branch = getattr(request.state, "branch_id", "")
    if role == UserRole.SUPER_ADMIN:
        return True
    if user_branch != branch_id:
        raise HTTPException(
            status_code=403,
            detail="You can only access data for your assigned branch",
        )
    return True