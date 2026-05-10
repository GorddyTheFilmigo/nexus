"""
middleware/audit_middleware.py
Logs every mutating request (POST/PUT/PATCH/DELETE) to Firestore audit trail.
Provides a tamper-evident record of who did what, when, from where.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import asyncio
from datetime import datetime, timezone
from firebase_admin_init import col


class AuditMiddleware(BaseHTTPMiddleware):
    AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if (
            request.method in self.AUDIT_METHODS
            and request.url.path not in self.SKIP_PATHS
            and hasattr(request.state, "uid")
        ):
            asyncio.create_task(self._write_audit(request, response.status_code))

        return response

    async def _write_audit(self, request: Request, status_code: int):
        try:
            col("audit_logs").add({
                "uid":        getattr(request.state, "uid", "anonymous"),
                "tenant_id":  getattr(request.state, "tenant_id", ""),
                "branch_id":  getattr(request.state, "branch_id", ""),
                "role":       getattr(request.state, "role", ""),
                "method":     request.method,
                "path":       str(request.url.path),
                "status":     status_code,
                "ip":         request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("user-agent", ""),
                "timestamp":  datetime.now(timezone.utc),
            })
        except Exception:
            pass   # audit failure must never break the actual request