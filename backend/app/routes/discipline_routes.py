from datetime import datetime, timezone

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from ..auth import roles_required
from ..db import get_db
from ..models import DisciplineUpdate, Student
from ..utils import (
    classify_discipline_update,
    compute_discipline_delta,
    create_notification,
    normalize_discipline_metrics,
    parse_uuid,
    recalculate_ranks,
    serialize_doc,
    validate_justification,
)


discipline_bp = Blueprint("discipline", __name__)


def _scope_student_or_404(db, student_id: str, claims: dict):
    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return None, ({"message": "Invalid student id"}, 400)

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return None, ({"message": "Student not found"}, 404)

    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return None, ({"message": "Forbidden"}, 403)

    return student, None


def _admin_actor():
    claims = get_jwt()
    admin_id = parse_uuid(get_jwt_identity())
    return {
        "id": str(admin_id) if admin_id else None,
        "name": claims.get("name"),
        "role": claims.get("role"),
        "college_id": claims.get("college_id"),
    }


@discipline_bp.post("/students/<student_id>/discipline-updates")
@roles_required("college_admin", "super_admin")
def create_discipline_update(student_id):
    db = get_db()
    claims = get_jwt()
    actor = _admin_actor()
    data = request.get_json(silent=True) or {}

    student, error = _scope_student_or_404(db, student_id, claims)
    if error:
        return error

    justification, err = validate_justification(data)
    if err:
        return {"message": err}, 400

    previous = normalize_discipline_metrics({}, fallback=serialize_doc(student))
    new = normalize_discipline_metrics(data, fallback=serialize_doc(student))
    delta = compute_discipline_delta(previous, new)

    if delta.get("behavior") == 0:
        return {"message": "No discipline metric changes detected"}, 400

    requires_approval, suspicious, flags = classify_discipline_update(delta, current_app.config)

    update_doc = DisciplineUpdate(
        student_id=student.id,
        college_id=student.college_id,
        department=student.department,
        year=student.year,
        created_at=datetime.now(timezone.utc),
        created_by={
            "id": actor["id"],
            "name": actor.get("name"),
            "role": actor.get("role"),
        },
        category=justification["category"],
        reason=justification["reason"],
        details=justification.get("details"),
        previous=previous,
        new=new,
        delta=delta,
        new_behavior=new.get("behavior"),
        new_discipline_score=new.get("discipline_score"),
        delta_behavior=delta.get("behavior"),
        delta_discipline_score=delta.get("discipline_score"),
        requires_approval=requires_approval,
        status="pending" if requires_approval else "applied",
        reviewed_by=None,
        reviewed_at=None,
        applied_at=None,
        suspicious=suspicious,
        suspicious_flags=flags,
    )

    db.add(update_doc)
    db.flush()

    if requires_approval:
        create_notification(
            db,
            {"id": student.id, "college_id": student.college_id},
            f"Discipline change pending approval for {student.name} (Δ {delta.get('discipline_score')}).",
            event_type="discipline_update_pending",
        )
        db.commit()
        return {"update": serialize_doc(update_doc)}, 202

    applied_at = datetime.now(timezone.utc)
    student.attendance = new["attendance"]
    student.behavior = new["behavior"]
    student.participation = new["participation"]
    student.discipline_score = new["discipline_score"]
    student.updated_at = applied_at

    update_doc.applied_at = applied_at
    update_doc.status = "applied"

    create_notification(
        db,
        {"id": student.id, "college_id": student.college_id},
        f"Discipline score updated for {student.name} to {new['discipline_score']}.",
        event_type="score_update",
    )
    db.commit()
    recalculate_ranks(db)

    return {
        "item": serialize_doc(student),
        "update": serialize_doc(update_doc),
    }, 200


@discipline_bp.get("/students/<student_id>/discipline-updates")
@roles_required("college_admin", "super_admin")
def list_discipline_updates(student_id):
    db = get_db()
    claims = get_jwt()

    student, error = _scope_student_or_404(db, student_id, claims)
    if error:
        return error

    query = db.query(DisciplineUpdate).filter(DisciplineUpdate.student_id == student.id)

    category = request.args.get("category")
    if category:
        query = query.filter(DisciplineUpdate.category == category)

    status = request.args.get("status")
    if status:
        query = query.filter(DisciplineUpdate.status == status)

    start = request.args.get("start")
    end = request.args.get("end")
    if start or end:
        try:
            if start:
                query = query.filter(DisciplineUpdate.created_at >= datetime.fromisoformat(start))
            if end:
                query = query.filter(DisciplineUpdate.created_at <= datetime.fromisoformat(end))
        except ValueError:
            return {"message": "Invalid date filter; use ISO format"}, 400

    direction = request.args.get("direction")
    if direction == "positive":
        query = query.filter(DisciplineUpdate.delta_discipline_score > 0)
    elif direction == "negative":
        query = query.filter(DisciplineUpdate.delta_discipline_score < 0)

    items = query.order_by(DisciplineUpdate.created_at.desc()).all()
    return {"items": [serialize_doc(x) for x in items]}, 200


@discipline_bp.get("/students/<student_id>/discipline-history")
def public_discipline_history(student_id):
    db = get_db()
    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    query = db.query(DisciplineUpdate).filter(
        DisciplineUpdate.student_id == student.id,
        DisciplineUpdate.status.in_(["applied", "approved"]),
    )

    category = request.args.get("category")
    if category:
        query = query.filter(DisciplineUpdate.category == category)

    start = request.args.get("start")
    end = request.args.get("end")
    if start or end:
        try:
            if start:
                query = query.filter(DisciplineUpdate.created_at >= datetime.fromisoformat(start))
            if end:
                query = query.filter(DisciplineUpdate.created_at <= datetime.fromisoformat(end))
        except ValueError:
            return {"message": "Invalid date filter; use ISO format"}, 400

    direction = request.args.get("direction")
    if direction == "positive":
        query = query.filter(DisciplineUpdate.delta_discipline_score > 0)
    elif direction == "negative":
        query = query.filter(DisciplineUpdate.delta_discipline_score < 0)

    items = query.order_by(DisciplineUpdate.created_at.desc()).all()

    results = []
    for item in items:
        payload = serialize_doc(item)
        created_by = payload.get("created_by") or {}
        payload["actor"] = {
            "name": created_by.get("name") or "Admin",
            "role": created_by.get("role") or "admin",
        }
        payload.pop("created_by", None)

        reviewed_by = payload.get("reviewed_by") or {}
        if reviewed_by:
            payload["reviewer"] = {
                "name": reviewed_by.get("name") or "Admin",
                "role": reviewed_by.get("role") or "admin",
            }
        payload.pop("reviewed_by", None)
        results.append(payload)

    return {"items": results}, 200


@discipline_bp.get("/discipline-updates/pending")
@roles_required("college_admin", "super_admin")
def pending_discipline_updates():
    db = get_db()
    claims = get_jwt()

    query = db.query(DisciplineUpdate).filter(DisciplineUpdate.status == "pending")
    if claims.get("role") == "college_admin":
        college_uuid = parse_uuid(claims.get("college_id"))
        if not college_uuid:
            return {"items": []}, 200
        query = query.filter(DisciplineUpdate.college_id == college_uuid)

    items = query.order_by(DisciplineUpdate.created_at.desc()).limit(100).all()

    student_ids = [item.student_id for item in items if item.student_id]
    students = {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()}

    results = []
    for item in items:
        payload = serialize_doc(item)
        st = students.get(item.student_id)
        payload["student"] = {
            "id": str(item.student_id) if item.student_id else None,
            "name": st.name if st else None,
            "roll_number": st.roll_number if st else None,
            "department": st.department if st else None,
        }
        results.append(payload)

    return {"items": results}, 200


@discipline_bp.post("/discipline-updates/<update_id>/approve")
@roles_required("college_admin", "super_admin")
def approve_discipline_update(update_id):
    db = get_db()
    claims = get_jwt()
    reviewer = _admin_actor()

    update_uuid = parse_uuid(update_id)
    if not update_uuid:
        return {"message": "Invalid update id"}, 400

    update_doc = db.query(DisciplineUpdate).filter(DisciplineUpdate.id == update_uuid).first()
    if not update_doc:
        return {"message": "Update not found"}, 404
    if update_doc.status != "pending":
        return {"message": "Update is not pending"}, 400

    student = db.query(Student).filter(Student.id == update_doc.student_id).first()
    if not student:
        return {"message": "Student not found"}, 404

    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    if str((update_doc.created_by or {}).get("id")) == str(reviewer.get("id")):
        return {"message": "You cannot approve your own discipline changes"}, 403

    applied_at = datetime.now(timezone.utc)
    new = update_doc.new or {}

    student.attendance = new.get("attendance", student.attendance or 0)
    student.behavior = new.get("behavior", student.behavior or 0)
    student.participation = new.get("participation", student.participation or 0)
    student.discipline_score = new.get("discipline_score", student.discipline_score or 0)
    student.updated_at = applied_at

    update_doc.status = "approved"
    update_doc.reviewed_by = {
        "id": reviewer["id"],
        "name": reviewer.get("name"),
        "role": reviewer.get("role"),
    }
    update_doc.reviewed_at = applied_at
    update_doc.applied_at = applied_at

    create_notification(
        db,
        {"id": student.id, "college_id": student.college_id},
        f"Discipline change approved for {student.name} (Score: {new.get('discipline_score')}).",
        event_type="discipline_update_approved",
    )
    db.commit()
    recalculate_ranks(db)

    return {"item": serialize_doc(student), "update": serialize_doc(update_doc)}, 200


@discipline_bp.post("/discipline-updates/<update_id>/reject")
@roles_required("college_admin", "super_admin")
def reject_discipline_update(update_id):
    db = get_db()
    claims = get_jwt()
    reviewer = _admin_actor()

    update_uuid = parse_uuid(update_id)
    if not update_uuid:
        return {"message": "Invalid update id"}, 400

    update_doc = db.query(DisciplineUpdate).filter(DisciplineUpdate.id == update_uuid).first()
    if not update_doc:
        return {"message": "Update not found"}, 404
    if update_doc.status != "pending":
        return {"message": "Update is not pending"}, 400

    student = db.query(Student).filter(Student.id == update_doc.student_id).first()
    if not student:
        return {"message": "Student not found"}, 404

    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    if str((update_doc.created_by or {}).get("id")) == str(reviewer.get("id")):
        return {"message": "You cannot reject your own discipline changes"}, 403

    rejected_at = datetime.now(timezone.utc)
    update_doc.status = "rejected"
    update_doc.reviewed_by = {
        "id": reviewer["id"],
        "name": reviewer.get("name"),
        "role": reviewer.get("role"),
    }
    update_doc.reviewed_at = rejected_at

    create_notification(
        db,
        {"id": student.id, "college_id": student.college_id},
        f"Discipline change rejected for {student.name}.",
        event_type="discipline_update_rejected",
    )
    db.commit()
    return {"update": serialize_doc(update_doc)}, 200
