"""
seed_firebase.py
Run once to bootstrap your Firebase project with:
  - Tenant document
  - Branch documents (Westlands, CBD, Kilimani)
  - Super Admin user in Firebase Auth + Firestore

Usage:
    py seed_firebase.py --email admin@yourcompany.co.ke --password YourPassword123
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore, auth as fb_auth

# ── Init ─────────────────────────────────────────────────────────────────────
SA_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "serviceAccount.json")
PROJECT  = os.environ.get("FIREBASE_PROJECT_ID", "nexus-c27e0")
TENANT_ID = os.environ.get("DEFAULT_TENANT_ID", "tenant-nexus-001")

if not os.path.exists(SA_PATH):
    print(f"\n❌  Service account file not found at: {SA_PATH}")
    print("   Download it from Firebase Console → Project Settings → Service Accounts → Generate new private key")
    print("   Save it as 'serviceAccount.json' in the backend/ folder.\n")
    sys.exit(1)

cred = credentials.Certificate(SA_PATH)
firebase_admin.initialize_app(cred, {"projectId": PROJECT})
db = firestore.client()

NOW = datetime.now(timezone.utc)


def seed_tenant():
    print("📦  Creating tenant...")
    ref = db.collection("tenants").document(TENANT_ID)
    ref.set({
        "tenant_id":  TENANT_ID,
        "name":       "Nexus Retail Ltd",
        "plan":       "enterprise",
        "country":    "KE",
        "currency":   "KES",
        "tax_rate":   0.16,
        "timezone":   "Africa/Nairobi",
        "created_at": NOW,
        "is_active":  True,
    }, merge=True)
    print(f"   ✓ Tenant: {TENANT_ID}")
    return ref


def seed_branches(tenant_ref):
    print("🏢  Creating branches...")
    branches = [
        {"branch_id": "branch-westlands", "name": "Westlands Branch",  "address": "Westlands, Nairobi", "phone": "+254700000001"},
        {"branch_id": "branch-cbd",       "name": "CBD Branch",        "address": "CBD, Nairobi",        "phone": "+254700000002"},
        {"branch_id": "branch-kilimani",  "name": "Kilimani Branch",   "address": "Kilimani, Nairobi",   "phone": "+254700000003"},
    ]
    for b in branches:
        ref = tenant_ref.collection("branches").document(b["branch_id"])
        ref.set({
            **b,
            "manager_id": None,
            "is_active":  True,
            "created_at": NOW,
        }, merge=True)
        print(f"   ✓ Branch: {b['name']} ({b['branch_id']})")
    return branches


def seed_products(tenant_ref):
    print("🛍️   Seeding sample products into Westlands branch...")
    products = [
        {"name": "Coca Cola 500ml",   "category": "Beverages", "price": 80,  "stock": 142, "unit": "piece"},
        {"name": "Bread Loaf",        "category": "Bakery",    "price": 65,  "stock": 34,  "unit": "piece"},
        {"name": "Mineral Water 1L",  "category": "Beverages", "price": 50,  "stock": 200, "unit": "piece"},
        {"name": "Unga Pembe 2kg",    "category": "Grains",    "price": 185, "stock": 8,   "unit": "bag"},
        {"name": "Sukari 1kg",        "category": "Grains",    "price": 130, "stock": 55,  "unit": "kg"},
        {"name": "Cooking Oil 500ml", "category": "Oils",      "price": 220, "stock": 0,   "unit": "piece"},
        {"name": "Milk 500ml",        "category": "Dairy",     "price": 55,  "stock": 90,  "unit": "piece"},
        {"name": "Eggs Tray 30",      "category": "Dairy",     "price": 480, "stock": 22,  "unit": "tray"},
        {"name": "Tomatoes 1kg",      "category": "Produce",   "price": 80,  "stock": 15,  "unit": "kg"},
        {"name": "Onions 1kg",        "category": "Produce",   "price": 60,  "stock": 40,  "unit": "kg"},
    ]
    col = (tenant_ref.collection("branches")
                     .document("branch-westlands")
                     .collection("products"))
    for p in products:
        import uuid
        pid = str(uuid.uuid4())
        col.document(pid).set({
            **p,
            "product_id":          pid,
            "tenant_id":           TENANT_ID,
            "branch_id":           "branch-westlands",
            "low_stock_threshold": 10,
            "created_at":          NOW,
            "updated_at":          NOW,
        })
    print(f"   ✓ {len(products)} products seeded into Westlands branch")


def seed_admin(email: str, password: str, tenant_ref):
    print(f"👤  Creating Super Admin: {email}")

    # Create or get Firebase Auth user
    try:
        user = fb_auth.get_user_by_email(email)
        print(f"   ℹ️  Auth user already exists (uid: {user.uid}) — updating...")
        fb_auth.update_user(user.uid, password=password, display_name="Admin")
    except fb_auth.UserNotFoundError:
        user = fb_auth.create_user(
            email=email,
            password=password,
            display_name="Admin",
            email_verified=True,
        )
        print(f"   ✓ Auth user created (uid: {user.uid})")

    # Set custom claims
    fb_auth.set_custom_user_claims(user.uid, {
        "role":      "super_admin",
        "tenant_id": TENANT_ID,
        "branch_id": "branch-westlands",
    })
    print("   ✓ Custom claims set (role: super_admin)")

    # Create Firestore profile
    db.collection("users").document(user.uid).set({
        "name":              "Admin",
        "email":             email,
        "role":              "super_admin",
        "branch_id":         "branch-westlands",
        "tenant_id":         TENANT_ID,
        "status":            "active",
        "created_at":        NOW,
        "created_by":        user.uid,
        "last_login":        None,
        "active_session_id": None,
    }, merge=True)
    print("   ✓ Firestore profile created")
    return user


def seed_tenant_settings(tenant_ref):
    print("⚙️   Writing tenant settings...")
    tenant_ref.collection("settings").document("general").set({
        "receipt_header": "NEXUS RETAIL LTD",
        "receipt_footer": "Asante sana! Thank you for shopping with us.",
        "tax_pin":        "P000000000A",
        "logo_url":       None,
        "printer_type":   "thermal_80mm",
    }, merge=True)
    print("   ✓ Settings written")


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Nexus POS Firebase project")
    parser.add_argument("--email",    required=True, help="Super admin email")
    parser.add_argument("--password", required=True, help="Super admin password (min 8 chars)")
    parser.add_argument("--skip-products", action="store_true", help="Skip seeding sample products")
    args = parser.parse_args()

    if len(args.password) < 8:
        print("❌  Password must be at least 8 characters")
        sys.exit(1)

    print(f"\n🚀  Seeding Firebase project: {PROJECT}\n{'─'*50}")

    tenant_ref = seed_tenant()
    seed_branches(tenant_ref)
    seed_tenant_settings(tenant_ref)
    if not args.skip_products:
        seed_products(tenant_ref)
    admin = seed_admin(args.email, args.password, tenant_ref)

    print(f"\n{'─'*50}")
    print("✅  Firebase seeded successfully!\n")
    print(f"   Project:   {PROJECT}")
    print(f"   Tenant ID: {TENANT_ID}")
    print(f"   Admin UID: {admin.uid}")
    print(f"   Email:     {args.email}")
    print(f"\n   Login at:  http://localhost:3000/login/")
    print(f"   API docs:  http://localhost:8000/docs\n")