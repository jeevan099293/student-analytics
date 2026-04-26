from datetime import datetime, timezone

from flask import Blueprint, request
from flask_jwt_extended import get_jwt, jwt_required

from ..auth import roles_required
from ..db import get_db
from ..models import College
from ..utils import parse_uuid, serialize_doc

colleges_bp = Blueprint("colleges", __name__)


@colleges_bp.get("")
@jwt_required(optional=True)
def list_colleges():
    db = get_db()
    claims = get_jwt() if request.headers.get("Authorization") else {}
    role = claims.get("role")

    if role == "college_admin":
        college_id = parse_uuid(claims.get("college_id"))
        if not college_id:
            return {"items": []}, 200
        colleges = db.query(College).filter(College.id == college_id).all()
    else:
        colleges = db.query(College).all()

    return {"items": [serialize_doc(c) for c in colleges]}, 200


@colleges_bp.post("")
@roles_required("super_admin")
def create_college():
    db = get_db()
    data = request.get_json(silent=True) or {}
    required = ["name", "location"]
    if any(not data.get(field) for field in required):
        return {"message": "Missing required fields"}, 400

    admin_ids = []
    for aid in data.get("admin_ids", []):
        parsed = parse_uuid(aid)
        if not parsed:
            return {"message": "Invalid admin_id in admin_ids"}, 400
        admin_ids.append(parsed)

    college = College(
        name=data["name"].strip(),
        location=data["location"].strip(),
        admin_ids=admin_ids,
        created_at=datetime.now(timezone.utc),
    )

    db.add(college)
    db.commit()
    return {"item": serialize_doc(college)}, 201


@colleges_bp.put("/<college_id>")
@roles_required("super_admin")
def update_college(college_id):
    db = get_db()
    data = request.get_json(silent=True) or {}

    updates = {}
    if "name" in data:
        updates["name"] = data["name"].strip()
    if "location" in data:
        updates["location"] = data["location"].strip()
    if "admin_ids" in data:
        admin_ids = []
        for aid in data["admin_ids"]:
            parsed = parse_uuid(aid)
            if not parsed:
                return {"message": "Invalid admin_id in admin_ids"}, 400
            admin_ids.append(parsed)
        updates["admin_ids"] = admin_ids

    if not updates:
        return {"message": "No fields to update"}, 400

    college_uuid = parse_uuid(college_id)
    if not college_uuid:
        return {"message": "Invalid college_id"}, 400

    college = db.query(College).filter(College.id == college_uuid).first()
    if not college:
        return {"message": "College not found"}, 404

    for key, value in updates.items():
        setattr(college, key, value)
    db.commit()
    return {"item": serialize_doc(college)}, 200


@colleges_bp.delete("/<college_id>")
@roles_required("super_admin")
def delete_college(college_id):
    db = get_db()
    college_uuid = parse_uuid(college_id)
    if not college_uuid:
        return {"message": "Invalid college_id"}, 400
    college = db.query(College).filter(College.id == college_uuid).first()
    if not college:
        return {"message": "College not found"}, 404
    db.delete(college)
    db.commit()
    return {"message": "College deleted"}, 200
