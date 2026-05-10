"""
firebase_admin_init.py — Server-side Firebase Admin SDK
The frontend NEVER gets direct Firestore/Auth access.
All reads/writes go through this module, called by FastAPI route handlers.
"""

import os
import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

_app = None


def get_firebase_app():
    global _app
    if _app is None:
        sa_path = os.environ.get(
            "FIREBASE_SERVICE_ACCOUNT_PATH", "serviceAccount.json"
        )
        cred = credentials.Certificate(sa_path)
        _app = firebase_admin.initialize_app(cred, {
            "projectId": "nexus-c27e0",
        })
    return _app


@lru_cache(maxsize=1)
def get_db() -> firestore.client:
    get_firebase_app()
    return firestore.client()


def get_auth():
    get_firebase_app()
    return firebase_auth


def col(name: str):
    return get_db().collection(name)


def tenant_col(tenant_id: str, name: str):
    """All data is namespaced under /tenants/{tenant_id}/..."""
    return (
        get_db()
        .collection("tenants")
        .document(tenant_id)
        .collection(name)
    )


def branch_col(tenant_id: str, branch_id: str, name: str):
    """Branch-scoped collection: /tenants/{tenant_id}/branches/{branch_id}/{name}"""
    return (
        get_db()
        .collection("tenants")
        .document(tenant_id)
        .collection("branches")
        .document(branch_id)
        .collection(name)
    )