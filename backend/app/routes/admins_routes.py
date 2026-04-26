from datetime import datetime, timezone

from flask import Blueprint, request

from ..auth import hash_password, roles_required
from ..db import get_db
from ..models import Admin
from ..utils import parse_uuid, serialize_doc

admins_bp = Blueprint("admins", __name__)


@admins_bp.get("")
@roles_required("super_admin")
def list_admins():
    db = get_db()
    admins = db.query(Admin).all()
    items = []
    for admin in admins:
        payload = serialize_doc(admin)
        payload.pop("password_hash", None)
        items.append(payload)
    return {"items": items}, 200


@admins_bp.post("")
@roles_required("super_admin")
def create_admin():
    db = get_db()
    data = request.get_json(silent=True) or {}

    required = ["name", "email", "password", "role"]
    if any(not data.get(field) for field in required):
        return {"message": "Missing required fields"}, 400

    if data["role"] != "college_admin":
        return {"message": "Only college_admin can be created"}, 400

    email = data["email"].strip().lower()
    if db.query(Admin).filter(Admin.email == email).first():
        return {"message": "Email already exists"}, 409

    college_id = data.get("college_id")
    if data["role"] == "college_admin" and not college_id:
        return {"message": "college_id is required for college_admin"}, 400

    college_uuid = parse_uuid(college_id) if college_id else None
    if college_id and not college_uuid:
        return {"message": "Invalid college_id"}, 400

    admin = Admin(
        name=data["name"].strip(),
        email=email,
        password_hash=hash_password(data["password"]),
        role=data["role"],
        college_id=college_uuid,
        created_at=datetime.now(timezone.utc),
    )

    db.add(admin)
    db.commit()
    payload = serialize_doc(admin)
    payload.pop("password_hash", None)
    return {"item": payload}, 201


@admins_bp.delete("/<admin_id>")
@roles_required("super_admin")
def delete_admin(admin_id):
    db = get_db()
    admin_uuid = parse_uuid(admin_id)
    if not admin_uuid:
        return {"message": "Invalid admin id"}, 400

    admin = db.query(Admin).filter(Admin.id == admin_uuid).first()
    if not admin:
        return {"message": "Admin not found"}, 404
    db.delete(admin)
    db.commit()
    return {"message": "Admin deleted"}, 200
