import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import or_

from ..auth import roles_required
from ..db import get_db
from ..models import College, DisciplineUpdate, Student
from ..utils import (
    create_notification,
    normalize_discipline_metrics,
    parse_uuid,
    recalculate_ranks,
    serialize_doc,
    validate_justification,
)

students_bp = Blueprint("students", __name__)


def _college_scope_filter(claims):
    if claims.get("role") == "college_admin":
        college_uuid = parse_uuid(claims.get("college_id"))
        if not college_uuid:
            return None, {"message": "Invalid college_id"}
        return [Student.college_id == college_uuid], None
    return [], None


def _student_dict(student, college_name=None):
    payload = serialize_doc(student)
    if college_name is not None:
        payload["college_name"] = college_name
    return payload


@students_bp.get("")
@roles_required("college_admin", "super_admin")
def list_students():
    db = get_db()
    claims = get_jwt()
    filters, err = _college_scope_filter(claims)
    if err:
        return err, 400

    college_id = request.args.get("college_id")
    department = request.args.get("department")
    year = request.args.get("year")
    search = request.args.get("search")

    if college_id and claims.get("role") == "super_admin":
        college_uuid = parse_uuid(college_id)
        if not college_uuid:
            return {"message": "Invalid college_id"}, 400
        filters.append(Student.college_id == college_uuid)
    if department:
        filters.append(Student.department == department.strip())
    if year:
        try:
            filters.append(Student.year == int(year))
        except ValueError:
            return {"message": "year must be a number"}, 400
    if search:
        like = f"%{search}%"
        filters.append(or_(Student.name.ilike(like), Student.roll_number.ilike(like)))
    if request.args.get("approved") in ["true", "false"]:
        filters.append(Student.approved == (request.args.get("approved") == "true"))

    items = db.query(Student).filter(*filters).all()
    college_ids = list({item.college_id for item in items if item.college_id})
    college_map = {}
    if college_ids:
        college_map = {
            c.id: c.name for c in db.query(College).filter(College.id.in_(college_ids)).all()
        }

    results = []
    for item in items:
        results.append(_student_dict(item, college_map.get(item.college_id)))

    return {"items": results}, 200


@students_bp.post("")
@roles_required("college_admin", "super_admin")
def create_student():
    db = get_db()
    data = request.get_json(silent=True) or {}
    claims = get_jwt()

    required = ["name", "roll_number", "department", "year", "behavior"]
    if any(data.get(field) is None or data.get(field) == "" for field in required):
        return {"message": "Missing required fields"}, 400

    college_id = data.get("college_id") or claims.get("college_id")
    if not college_id:
        return {"message": "college_id is required"}, 400

    college_uuid = parse_uuid(college_id)
    if not college_uuid:
        return {"message": "Invalid college_id"}, 400

    if claims.get("role") == "college_admin" and college_id != claims.get("college_id"):
        return {"message": "You can only create students in your college"}, 403

    metrics = normalize_discipline_metrics(data)
    attendance = metrics["attendance"]
    behavior = metrics["behavior"]
    participation = metrics["participation"]
    score = metrics["discipline_score"]

    if (
        db.query(Student)
        .filter(Student.roll_number == data["roll_number"].strip(), Student.college_id == college_uuid)
        .first()
    ):
        return {"message": "Roll number already exists in this college"}, 409

    admin_id = parse_uuid(get_jwt_identity())
    if not admin_id:
        return {"message": "Invalid admin id"}, 400

    payload = Student(
        name=data["name"].strip(),
        roll_number=data["roll_number"].strip(),
        college_id=college_uuid,
        department=data["department"].strip(),
        year=int(data["year"]),
        bio=(data.get("bio") or "").strip() or None,
        contact_email=(data.get("contact_email") or "").strip() or None,
        contact_phone=(data.get("contact_phone") or "").strip() or None,
        attendance=attendance,
        behavior=behavior,
        participation=participation,
        achievements=data.get("achievements", []),
        discipline_score=score,
        rank_global=None,
        rank_college=None,
        rank_department=None,
        approved=False,
        approved_by=None,
        approved_at=None,
        history=[
            {
                "timestamp": datetime.now(timezone.utc),
                "updated_by": str(admin_id),
                "reason": "created",
                "category": "Other",
                "previous": {},
                "new": {
                    "attendance": attendance,
                    "behavior": behavior,
                    "participation": participation,
                    "discipline_score": score,
                },
            }
        ],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    db.add(payload)
    db.flush()

    update_doc = DisciplineUpdate(
        student_id=payload.id,
        college_id=payload.college_id,
        department=payload.department,
        year=payload.year,
        created_at=datetime.now(timezone.utc),
        created_by={
            "id": str(admin_id),
            "name": claims.get("name"),
            "role": claims.get("role"),
        },
        category="Other",
        reason="created",
        details=None,
        previous={},
        new={
            "attendance": attendance,
            "behavior": behavior,
            "participation": participation,
            "discipline_score": score,
        },
        delta={
            "attendance": attendance,
            "behavior": behavior,
            "participation": participation,
            "discipline_score": score,
        },
        new_behavior=behavior,
        new_discipline_score=score,
        delta_behavior=behavior,
        delta_discipline_score=score,
        requires_approval=False,
        status="applied",
        reviewed_by=None,
        reviewed_at=None,
        applied_at=datetime.now(timezone.utc),
        suspicious=False,
        suspicious_flags=[],
    )

    db.add(update_doc)
    create_notification(
        db,
        {"id": payload.id, "college_id": payload.college_id},
        f"New student record created for {payload.name} ({payload.roll_number}).",
        event_type="student_created",
    )
    db.commit()
    recalculate_ranks(db)

    return {"item": serialize_doc(payload)}, 201


@students_bp.get("/<student_id>")
@jwt_required(optional=True)
def get_student(student_id):
    db = get_db()
    claims = get_jwt() if request.headers.get("Authorization") else {}
    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    college_name = None
    if student.college_id:
        from ..models import College

        college = db.query(College).filter(College.id == student.college_id).first()
        college_name = college.name if college else None

    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    if not claims:
        public_fields = {
            "id": student.id,
            "name": student.name,
            "department": student.department,
            "year": student.year,
            "college_id": student.college_id,
            "college_name": college_name,
            "bio": student.bio,
            "contact_email": student.contact_email,
            "contact_phone": student.contact_phone,
            "discipline_score": student.discipline_score,
            "rank_global": student.rank_global,
            "rank_college": student.rank_college,
            "rank_department": student.rank_department,
            "behavior": student.behavior,
        }
        return {"item": serialize_doc(public_fields)}, 200

    return {"item": _student_dict(student, college_name)}, 200


@students_bp.put("/<student_id>")
@roles_required("college_admin", "super_admin")
def update_student(student_id):
    db = get_db()
    claims = get_jwt()
    data = request.get_json(silent=True) or {}

    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    updates = {}
    for field in ["name", "department", "year", "achievements", "bio", "contact_email", "contact_phone", "photo_url"]:
        if field in data:
            updates[field] = data[field]

    metrics_changed = any(k in data for k in ["behavior"])
    if metrics_changed:
        return {
            "message": "Discipline metrics must be updated via /students/<id>/discipline-updates with justification",
        }, 400

    if claims.get("role") == "super_admin" and "college_id" in data:
        college_uuid = parse_uuid(data["college_id"])
        if not college_uuid:
            return {"message": "Invalid college_id"}, 400
        updates["college_id"] = college_uuid

    updates["updated_at"] = datetime.now(timezone.utc)
    for key, value in updates.items():
        setattr(student, key, value)

    db.commit()
    recalculate_ranks(db)

    updated = db.query(Student).filter(Student.id == student_uuid).first()
    return {"item": serialize_doc(updated)}, 200


@students_bp.put("/me")
def student_self_update():
    db = get_db()
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    if not student_id:
        return {"message": "student_id is required"}, 400

    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    updates = {}
    for field in ["contact_email", "photo_url", "bio"]:
        if field in data:
            updates[field] = data[field]

    if not updates:
        return {"message": "No fields to update"}, 400

    updates["updated_at"] = datetime.now(timezone.utc)
    for key, value in updates.items():
        setattr(student, key, value)

    db.commit()
    return {"message": "Profile updated successfully"}, 200


@students_bp.delete("/<student_id>")
@roles_required("college_admin", "super_admin")
def delete_student(student_id):
    db = get_db()
    claims = get_jwt()

    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404
    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    create_notification(
        db,
        {"id": student.id, "college_id": student.college_id},
        f"Student record deleted for {student.name}.",
        event_type="student_deleted",
    )
    db.delete(student)
    db.commit()
    recalculate_ranks(db)
    return {"message": "Student deleted"}, 200


@students_bp.post("/bulk-upload")
@roles_required("college_admin", "super_admin")
def bulk_upload_students():
    db = get_db()
    claims = get_jwt()
    admin_id = parse_uuid(get_jwt_identity())
    if not admin_id:
        return {"message": "Invalid admin id"}, 400

    if "file" not in request.files:
        return {"message": "CSV file is required"}, 400

    file = request.files["file"]
    content = file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    inserted_count = 0
    for row in reader:
        college_id = row.get("college_id") or claims.get("college_id")
        if not college_id:
            continue

        college_uuid = parse_uuid(college_id)
        if not college_uuid:
            continue

        if claims.get("role") == "college_admin" and college_id != claims.get("college_id"):
            continue

        metrics = normalize_discipline_metrics(row)
        attendance = metrics["attendance"]
        behavior = metrics["behavior"]
        participation = metrics["participation"]
        score = metrics["discipline_score"]

        payload = Student(
            name=row.get("name", "").strip(),
            roll_number=row.get("roll_number", "").strip(),
            college_id=college_uuid,
            department=row.get("department", "General").strip(),
            year=int(row.get("year", 1)),
            attendance=attendance,
            behavior=behavior,
            participation=participation,
            discipline_score=score,
            rank_global=None,
            rank_college=None,
            rank_department=None,
            achievements=[],
            history=[
                {
                    "timestamp": datetime.now(timezone.utc),
                    "updated_by": str(admin_id),
                    "reason": "bulk_upload",
                    "category": "Other",
                    "previous": {},
                    "new": {
                        "attendance": attendance,
                        "behavior": behavior,
                        "participation": participation,
                        "discipline_score": score,
                    },
                }
            ],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        if payload.name and payload.roll_number:
            existing = (
                db.query(Student)
                .filter(Student.roll_number == payload.roll_number, Student.college_id == payload.college_id)
                .first()
            )
            if not existing:
                db.add(payload)
                db.flush()

                db.add(
                    DisciplineUpdate(
                        student_id=payload.id,
                        college_id=payload.college_id,
                        department=payload.department,
                        year=payload.year,
                        created_at=datetime.now(timezone.utc),
                        created_by={
                            "id": str(admin_id),
                            "name": claims.get("name"),
                            "role": claims.get("role"),
                        },
                        category="Other",
                        reason="bulk_upload",
                        details=None,
                        previous={},
                        new={
                            "attendance": attendance,
                            "behavior": behavior,
                            "participation": participation,
                            "discipline_score": score,
                        },
                        delta={
                            "attendance": attendance,
                            "behavior": behavior,
                            "participation": participation,
                            "discipline_score": score,
                        },
                        new_behavior=behavior,
                        new_discipline_score=score,
                        delta_behavior=behavior,
                        delta_discipline_score=score,
                        requires_approval=False,
                        status="applied",
                        reviewed_by=None,
                        reviewed_at=None,
                        applied_at=datetime.now(timezone.utc),
                        suspicious=False,
                        suspicious_flags=[],
                    )
                )
                create_notification(
                    db,
                    {"id": payload.id, "college_id": payload.college_id},
                    f"Student {payload.name} was added via CSV bulk upload.",
                    event_type="bulk_upload",
                )
                inserted_count += 1

    db.commit()
    recalculate_ranks(db)
    return {"message": "Bulk upload completed", "inserted_count": inserted_count}, 200


@students_bp.post("/reset-scores")
@roles_required("college_admin", "super_admin")
def reset_scores():
    db = get_db()
    claims = get_jwt()
    data = request.get_json(silent=True) or {}
    justification, err = validate_justification(data)
    if err:
        return {"message": err}, 400

    college_id = (data.get("college_id") or "").strip()
    roll_number = (data.get("roll_number") or "").strip()

    if not college_id or not roll_number:
        return {"message": "college_id and roll_number are required"}, 400

    if claims.get("role") == "college_admin" and college_id != claims.get("college_id"):
        return {"message": "You can only reset scores in your college"}, 403

    college_uuid = parse_uuid(college_id)
    if not college_uuid:
        return {"message": "Invalid college_id"}, 400

    students = (
        db.query(Student)
        .filter(Student.college_id == college_uuid, Student.roll_number == roll_number)
        .all()
    )
    if not students:
        return {"message": "No student found for provided college and roll number"}, 404

    admin_id = parse_uuid(get_jwt_identity())
    if not admin_id:
        return {"message": "Invalid admin id"}, 400

    for student in students:
        applied_at = datetime.now(timezone.utc)
        previous = normalize_discipline_metrics({}, fallback=serialize_doc(student))

        student.attendance = 0
        student.behavior = 0
        student.participation = 0
        student.discipline_score = 0
        student.updated_at = applied_at
        history = list(student.history or [])
        history.append(
            {
                "timestamp": applied_at,
                "updated_by": str(admin_id),
                "reason": justification["reason"],
                "category": justification["category"],
                "details": justification.get("details"),
                "previous": {
                    "attendance": previous.get("attendance", 0),
                    "behavior": previous.get("behavior", 0),
                    "participation": previous.get("participation", 0),
                    "discipline_score": previous.get("discipline_score", 0),
                },
                "new": {
                    "attendance": 0,
                    "behavior": 0,
                    "participation": 0,
                    "discipline_score": 0,
                },
            }
        )
        student.history = history

        db.add(
            DisciplineUpdate(
                student_id=student.id,
                college_id=student.college_id,
                department=student.department,
                year=student.year,
                created_at=applied_at,
                created_by={
                    "id": str(admin_id),
                    "name": claims.get("name"),
                    "role": claims.get("role"),
                },
                category=justification["category"],
                reason=justification["reason"],
                details=justification.get("details"),
                previous=previous,
                new={
                    "attendance": 0,
                    "behavior": 0,
                    "participation": 0,
                    "discipline_score": 0,
                },
                delta={
                    "attendance": -previous.get("attendance", 0),
                    "behavior": -previous.get("behavior", 0),
                    "participation": -previous.get("participation", 0),
                    "discipline_score": -previous.get("discipline_score", 0),
                },
                new_behavior=0,
                new_discipline_score=0,
                delta_behavior=-previous.get("behavior", 0),
                delta_discipline_score=-previous.get("discipline_score", 0),
                requires_approval=False,
                status="applied",
                reviewed_by=None,
                reviewed_at=None,
                applied_at=applied_at,
                suspicious=False,
                suspicious_flags=[],
            )
        )

        create_notification(
            db,
            {"id": student.id, "college_id": student.college_id},
            f"Scores reset for {student.name}.",
            event_type="score_reset",
        )

    db.commit()
    recalculate_ranks(db)
    return {"message": "Score reset successfully", "count": len(students)}, 200


@students_bp.post("/<student_id>/approve")
@roles_required("college_admin", "super_admin")
def approve_student(student_id):
    db = get_db()
    claims = get_jwt()
    approver_id = parse_uuid(get_jwt_identity())
    if not approver_id:
        return {"message": "Invalid admin id"}, 400

    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404
    if claims.get("role") == "college_admin" and str(student.college_id) != claims.get("college_id"):
        return {"message": "Forbidden"}, 403

    student.approved = True
    student.approved_by = approver_id
    student.approved_at = datetime.now(timezone.utc)
    student.updated_at = datetime.now(timezone.utc)

    history = list(student.history or [])
    history.append(
        {
            "timestamp": datetime.now(timezone.utc),
            "updated_by": str(approver_id),
            "reason": "approved",
            "new": {"approved": True},
        }
    )
    student.history = history

    create_notification(
        db,
        {"id": student.id, "college_id": student.college_id},
        f"Student profile approved for {student.name}.",
        event_type="student_approved",
    )
    db.commit()
    updated = db.query(Student).filter(Student.id == student_uuid).first()
    return {"item": serialize_doc(updated)}, 200
