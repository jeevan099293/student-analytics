from flask import Blueprint, request
from sqlalchemy import asc, desc

from ..db import get_db
from ..models import College, Student
from ..utils import parse_uuid, serialize_doc

leaderboard_bp = Blueprint("leaderboard", __name__)


def _build_filters(base_filters=None):
    filters = base_filters or []
    college_id = request.args.get("college_id")
    department = request.args.get("department")
    year = request.args.get("year")
    search = request.args.get("search")

    if college_id:
        parsed = parse_uuid(college_id)
        if parsed:
            filters.append(Student.college_id == parsed)
    if department:
        filters.append(Student.department == department.strip())
    if year:
        try:
            filters.append(Student.year == int(year))
        except ValueError:
            pass
    if search:
        like = f"%{search}%"
        filters.append((Student.name.ilike(like)) | (Student.roll_number.ilike(like)))
    return filters


@leaderboard_bp.get("/global")
def global_leaderboard():
    db = get_db()
    filters = _build_filters()
    sort_by = request.args.get("sort_by", "discipline_score")
    sort_column = Student.discipline_score if sort_by == "discipline_score" else Student.name
    students = (
        db.query(Student)
        .filter(*filters)
        .order_by(desc(sort_column), asc(Student.name))
        .all()
    )

    college_ids = list({s.college_id for s in students if s.college_id})
    colleges = (
        db.query(College.id, College.name)
        .filter(College.id.in_(college_ids))
        .all()
    )
    college_map = {cid: name for cid, name in colleges}

    items = []
    for s in students:
        payload = serialize_doc(s)
        payload["college_name"] = college_map.get(s.college_id)
        items.append(payload)

    return {"items": items}, 200


@leaderboard_bp.get("/college/<college_id>")
def college_leaderboard(college_id):
    db = get_db()
    college_uuid = parse_uuid(college_id)
    if not college_uuid:
        return {"message": "Invalid college_id"}, 400
    filters = _build_filters([Student.college_id == college_uuid])
    students = (
        db.query(Student)
        .filter(*filters)
        .order_by(desc(Student.discipline_score), asc(Student.name))
        .all()
    )
    college = db.query(College).filter(College.id == college_uuid).first()
    items = []
    for s in students:
        payload = serialize_doc(s)
        payload["college_name"] = college.name if college else None
        items.append(payload)
    return {"items": items}, 200


@leaderboard_bp.get("/department")
def department_leaderboard():
    db = get_db()
    college_id = request.args.get("college_id")
    department = request.args.get("department")
    if not college_id or not department:
        return {"message": "college_id and department are required"}, 400

    college_uuid = parse_uuid(college_id)
    if not college_uuid:
        return {"message": "Invalid college_id"}, 400

    students = (
        db.query(Student)
        .filter(Student.college_id == college_uuid, Student.department == department)
        .order_by(desc(Student.discipline_score), asc(Student.name))
        .all()
    )
    college = db.query(College).filter(College.id == college_uuid).first()
    items = []
    for s in students:
        payload = serialize_doc(s)
        payload["college_name"] = college.name if college else None
        items.append(payload)
    return {"items": items}, 200
