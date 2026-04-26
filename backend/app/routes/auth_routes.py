from datetime import datetime, timezone
from uuid import UUID

from flask import Blueprint, current_app, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required

from ..auth import hash_password, verify_password
from ..db import get_db
from ..models import Admin
from ..utils import serialize_doc

auth_bp = Blueprint("auth", __name__)


def _parse_uuid(value: str):
    try:
        return UUID(value)
    except Exception:
        return None


def ensure_bootstrap_super_admin(db):
    email = current_app.config["SUPER_ADMIN_EMAIL"]
    existing = db.query(Admin).filter(Admin.email == email).first()
    payload = {
        "name": "Platform Super Admin",
        "password_hash": hash_password(current_app.config["SUPER_ADMIN_PASSWORD"]),
        "role": "super_admin",
        "college_id": None,
    }
    if existing:
        existing.name = payload["name"]
        existing.password_hash = payload["password_hash"]
        existing.role = payload["role"]
        existing.college_id = payload["college_id"]
        db.commit()
        return

    admin = Admin(
        name=payload["name"],
        email=email,
        password_hash=payload["password_hash"],
        role=payload["role"],
        college_id=payload["college_id"],
        created_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    db.commit()


@auth_bp.post("/login")
def login():
    db = get_db()
    ensure_bootstrap_super_admin(db)
    data = request.get_json(silent=True) or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin or not verify_password(admin.password_hash or "", password):
        return {"message": "Invalid credentials"}, 401

    token = create_access_token(
        identity=str(admin.id),
        additional_claims={
            "role": admin.role,
            "college_id": str(admin.college_id) if admin.college_id else None,
            "name": admin.name,
        },
    )

    return {
        "access_token": token,
        "admin": {
            "id": str(admin.id),
            "name": admin.name,
            "email": admin.email,
            "role": admin.role,
            "college_id": str(admin.college_id) if admin.college_id else None,
        },
    }, 200


@auth_bp.get("/me")
@jwt_required()
def me():
    db = get_db()
    admin_id = get_jwt_identity()
    parsed_id = _parse_uuid(admin_id)
    if not parsed_id:
        return {"message": "Invalid admin id"}, 400
    admin = db.query(Admin).filter(Admin.id == parsed_id).first()
    if not admin:
        return {"message": "Admin not found"}, 404
    admin_doc = serialize_doc(admin)
    admin_doc.pop("password_hash", None)
    return {"admin": admin_doc}, 200
