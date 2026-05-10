"""
middleware/auth_middleware.py
Validates Firebase ID tokens on every protected request.
Public routes are whitelisted.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from firebase_admin import auth as firebase_auth
from firebase_admin_init import get_firebase_app
import traceback

# ── Routes that do NOT require a token ───────────────────────────────────────
PUBLIC_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/login",
    "/api/v1/auth/register",      # Registration handles its own token verification
    "/api/v1/auth/refresh",
}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Always allow OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow public paths without authentication
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        # All other routes require Bearer token
        auth_header = request.headers.get("Authorization", "")
        
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header. Use Bearer token."}
            )

        id_token = auth_header.split("Bearer ")[1].strip()

        try:
            # Ensure Firebase is initialized
            get_firebase_app()
            
            # Verify token
            decoded = firebase_auth.verify_id_token(
                id_token, 
                check_revoked=True
            )
            
            # Attach user info to request state
            request.state.uid = decoded["uid"]
            request.state.email = decoded.get("email", "")
            request.state.tenant_id = decoded.get("tenant_id", "")
            request.state.branch_id = decoded.get("branch_id", "")
            request.state.role = decoded.get("role", "cashier")
            request.state.token_claims = decoded

        except firebase_auth.ExpiredIdTokenError:
            return JSONResponse(
                status_code=401,
                content={"error": "Token expired. Please log in again."}
            )
        except firebase_auth.InvalidIdTokenError:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid Firebase ID token."}
            )
        except firebase_auth.RevokedIdTokenError:
            return JSONResponse(
                status_code=401,
                content={"error": "Token has been revoked. Please log in again."}
            )
        except Exception as e:
            print(f"Auth middleware error: {e}")
            traceback.print_exc()
            return JSONResponse(
                status_code=401,
                content={"error": "Authentication failed", "detail": str(e)}
            )

        return await call_next(request)