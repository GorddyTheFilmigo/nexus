"""
Nexus POS — FastAPI Backend
All Firebase operations are server-side only. Frontend never touches Firebase directly.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from routers import auth, users, sales, inventory, reports, sessions
from middleware.auth_middleware import AuthMiddleware
from middleware.audit_middleware import AuditMiddleware

app = FastAPI(
    title="Nexus POS API",
    version="1.0.0",
    description="Multi-tenant POS backend — Firebase operations are server-side only",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Note: allow_credentials=True cannot be combined with allow_origins=["*"]
# We use ["*"] without credentials — the token is sent in Authorization header
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── CUSTOM MIDDLEWARE ────────────────────────────────────────────────────────
app.add_middleware(AuthMiddleware)
app.add_middleware(AuditMiddleware)

# ─── ROUTERS ─────────────────────────────────────────────────────────────────
app.include_router(auth.router,      prefix="/api/v1/auth",      tags=["Auth"])
app.include_router(users.router,     prefix="/api/v1/users",     tags=["Users"])
app.include_router(sales.router,     prefix="/api/v1/sales",     tags=["Sales"])
app.include_router(inventory.router, prefix="/api/v1/inventory", tags=["Inventory"])
app.include_router(reports.router,   prefix="/api/v1/reports",   tags=["Reports"])
app.include_router(sessions.router,  prefix="/api/v1/sessions",  tags=["Sessions"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nexus-pos-api"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)