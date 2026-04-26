from flask import Blueprint
from flask_jwt_extended import get_jwt
from sqlalchemy import desc

from ..auth import roles_required
from ..db import get_db
from ..models import Notification
from ..utils import parse_uuid, serialize_doc

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.get("")
@roles_required("college_admin", "super_admin")
def list_notifications():
    db = get_db()
    claims = get_jwt()

    query = db.query(Notification)
    if claims.get("role") == "college_admin":
        college_uuid = parse_uuid(claims.get("college_id"))
        if not college_uuid:
            return {"items": [], "unread_count": 0}, 200
        query = query.filter(Notification.college_id == college_uuid)

    items = query.order_by(desc(Notification.created_at)).limit(50).all()
    unread = query.filter(Notification.is_read.is_(False)).count()
    return {"items": [serialize_doc(item) for item in items], "unread_count": unread}, 200


@notifications_bp.patch("/<notification_id>/read")
@roles_required("college_admin", "super_admin")
def mark_as_read(notification_id):
    db = get_db()
    claims = get_jwt()
    notification_uuid = parse_uuid(notification_id)
    if not notification_uuid:
        return {"message": "Invalid notification id"}, 400

    notification = db.query(Notification).filter(Notification.id == notification_uuid).first()
    if not notification:
        return {"message": "Notification not found"}, 404

    if claims.get("role") == "college_admin" and str(notification.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    notification.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}, 200
