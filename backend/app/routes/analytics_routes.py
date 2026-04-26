from datetime import datetime, timedelta, timezone

from flask import Blueprint, request
from sqlalchemy import func

from ..auth import roles_required
from ..db import get_db
from ..models import DisciplineUpdate, Student
from ..utils import parse_uuid


analytics_bp = Blueprint("analytics", __name__)


def _iso(dt):
    return dt.isoformat() if isinstance(dt, datetime) else None


def _trend_label(delta_score: float) -> str:
    if delta_score > 0:
        return "improving"
    if delta_score < 0:
        return "declining"
    return "stable"


def _safe_int(value: str):
    try:
        return int(value)
    except Exception:
        return None


def _admin_scope_filters():
    from flask_jwt_extended import get_jwt

    claims = get_jwt()
    role = claims.get("role")

    students_filters = []
    updates_filters = [DisciplineUpdate.status.in_(["applied", "approved"])]

    if role == "college_admin" and claims.get("college_id"):
        cid = parse_uuid(claims.get("college_id"))
        if cid:
            students_filters.append(Student.college_id == cid)
            updates_filters.append(DisciplineUpdate.college_id == cid)

    college_id = request.args.get("college_id")
    department = request.args.get("department")
    year = request.args.get("year")

    if college_id:
        cid = parse_uuid(college_id)
        if cid:
            students_filters.append(Student.college_id == cid)
            updates_filters.append(DisciplineUpdate.college_id == cid)

    if department:
        students_filters.append(Student.department == department.strip())
        updates_filters.append(DisciplineUpdate.department == department.strip())

    if year:
        y = _safe_int(year)
        if y is not None:
            students_filters.append(Student.year == y)
            updates_filters.append(DisciplineUpdate.year == y)

    return students_filters, updates_filters


@analytics_bp.get("/dashboard")
@roles_required("college_admin", "super_admin")
def analytics_dashboard():
    db = get_db()
    students_filters, updates_filters = _admin_scope_filters()

    now = datetime.now(timezone.utc)
    daily_start = now - timedelta(days=84)
    monthly_start = now - timedelta(days=365)

    kpi = (
        db.query(
            func.count(Student.id),
            func.avg(Student.discipline_score),
            func.avg(Student.behavior),
            func.min(Student.rank_global),
            func.min(Student.rank_college),
        )
        .filter(*students_filters)
        .first()
    )

    def _r(v, nd=2):
        try:
            return round(float(v or 0), nd)
        except Exception:
            return 0

    kpis = {
        "students": int(kpi[0] or 0),
        "avg": {
            "discipline_score": _r(kpi[1], 2),
            "behavior": _r(kpi[2], 2),
        },
        "best": {
            "rank_global": int(kpi[3]) if kpi[3] is not None else None,
            "rank_college": int(kpi[4]) if kpi[4] is not None else None,
        },
    }

    updates = (
        db.query(DisciplineUpdate)
        .filter(*updates_filters, DisciplineUpdate.created_at >= daily_start, DisciplineUpdate.created_at <= now)
        .order_by(DisciplineUpdate.created_at.asc())
        .all()
    )

    daily_map = {}
    for u in updates:
        key = u.created_at.date().isoformat()
        if key not in daily_map:
            daily_map[key] = {"updates": 0, "discipline_score": [], "behavior": []}
        daily_map[key]["updates"] += 1
        if u.new_discipline_score is not None:
            daily_map[key]["discipline_score"].append(u.new_discipline_score)
        if u.new_behavior is not None:
            daily_map[key]["behavior"].append(u.new_behavior)

    daily_series = []
    for date_key in sorted(daily_map.keys()):
        entry = daily_map[date_key]
        ds_avg = sum(entry["discipline_score"]) / max(len(entry["discipline_score"]), 1)
        beh_avg = sum(entry["behavior"]) / max(len(entry["behavior"]), 1)
        daily_series.append(
            {
                "date": date_key,
                "updates": int(entry["updates"]),
                "discipline_score": _r(ds_avg, 2),
                "behavior": _r(beh_avg, 2),
            }
        )

    monthly_updates = (
        db.query(DisciplineUpdate)
        .filter(*updates_filters, DisciplineUpdate.created_at >= monthly_start, DisciplineUpdate.created_at <= now)
        .order_by(DisciplineUpdate.created_at.asc())
        .all()
    )

    monthly_map = {}
    for u in monthly_updates:
        key = u.created_at.strftime("%Y-%m")
        monthly_map.setdefault(key, []).append(u.new_behavior or 0)

    monthly_behavior = [
        {"month": month, "behavior": _r(sum(vals) / max(len(vals), 1), 2)}
        for month, vals in sorted(monthly_map.items())
    ]

    def _avg(items, key):
        if not items:
            return 0
        return sum(float(x.get(key, 0) or 0) for x in items) / len(items)

    last7 = daily_series[-7:]
    prev7 = daily_series[-14:-7]

    trends = {
        "weekly": {
            "discipline_score": _r(_avg(last7, "discipline_score") - _avg(prev7, "discipline_score"), 2),
            "behavior": _r(_avg(last7, "behavior") - _avg(prev7, "behavior"), 2),
        }
    }

    total_reports = (
        db.query(DisciplineUpdate)
        .filter(*updates_filters, DisciplineUpdate.created_at >= monthly_start, DisciplineUpdate.created_at <= now)
        .count()
    )

    improvement_rate = 0
    if len(daily_series) >= 2:
        first = daily_series[0].get("discipline_score", 0)
        last = daily_series[-1].get("discipline_score", 0)
        if float(first) != 0:
            improvement_rate = _r(((float(last) - float(first)) / abs(float(first))) * 100.0, 2)

    performance = {
        "total_reports": int(total_reports or 0),
        "weekly_performance_score": _r(_avg(last7, "discipline_score"), 2),
        "improvement_rate": improvement_rate,
    }

    return {
        "kpis": kpis,
        "trends": trends,
        "daily": daily_series,
        "monthly_behavior": monthly_behavior,
        "performance": performance,
        "generated_at": _iso(now),
    }, 200


@analytics_bp.get("/recent-activity")
@roles_required("college_admin", "super_admin")
def recent_activity():
    db = get_db()
    _, updates_filters = _admin_scope_filters()

    items = (
        db.query(DisciplineUpdate)
        .filter(*updates_filters)
        .order_by(DisciplineUpdate.created_at.desc())
        .limit(20)
        .all()
    )

    student_ids = [i.student_id for i in items if i.student_id]
    students = {s.id: s for s in db.query(Student).filter(Student.id.in_(student_ids)).all()}

    result = []
    for it in items:
        st = students.get(it.student_id) or None
        created_by = it.created_by or {}
        result.append(
            {
                "id": str(it.id),
                "timestamp": _iso(it.applied_at or it.created_at),
                "student": {
                    "id": str(it.student_id) if it.student_id else None,
                    "name": st.name if st else None,
                    "roll_number": st.roll_number if st else None,
                    "department": st.department if st else None,
                    "year": st.year if st else None,
                },
                "category": it.category,
                "reason": it.reason,
                "delta": it.delta_discipline_score,
                "status": it.status,
                "actor": {
                    "name": created_by.get("name") or "Admin",
                    "role": created_by.get("role") or "admin",
                },
                "suspicious": bool(it.suspicious),
            }
        )

    return {"items": result}, 200


@analytics_bp.get("/trends/<student_id>")
@roles_required("college_admin", "super_admin")
def score_trends(student_id):
    db = get_db()
    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    items = (
        db.query(DisciplineUpdate)
        .filter(
            DisciplineUpdate.student_id == student.id,
            DisciplineUpdate.status.in_(["applied", "approved"]),
        )
        .order_by(DisciplineUpdate.created_at.asc())
        .all()
    )

    trends = []
    for item in items:
        trends.append(
            {
                "timestamp": item.applied_at or item.created_at,
                "discipline_score": item.new_discipline_score,
                "behavior": item.new_behavior,
            }
        )
    return {"student_id": student_id, "student_name": student.name, "trends": trends}, 200


@analytics_bp.get("/weekly-report")
@roles_required("college_admin", "super_admin")
def weekly_report():
    db = get_db()
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    items = (
        db.query(DisciplineUpdate)
        .filter(
            DisciplineUpdate.created_at >= one_week_ago,
            DisciplineUpdate.status.in_(["applied", "approved"]),
        )
        .all()
    )

    report_map = {}
    for item in items:
        key = str(item.college_id)
        report_map.setdefault(key, {"updates_count": 0, "scores": []})
        report_map[key]["updates_count"] += 1
        report_map[key]["scores"].append(item.new_discipline_score or 0)

    report = []
    for college_id, data in report_map.items():
        avg_score = sum(data["scores"]) / max(len(data["scores"]), 1)
        report.append(
            {
                "college_id": college_id,
                "updates_count": data["updates_count"],
                "avg_score": round(avg_score, 2),
            }
        )

    return {"items": report}, 200


@analytics_bp.get("/badges")
@roles_required("college_admin", "super_admin")
def badges():
    db = get_db()
    best_discipline = db.query(Student).order_by(Student.discipline_score.desc()).first()
    best_behavior = db.query(Student).order_by(Student.behavior.desc()).first()

    result = {
        "best_discipline": {
            "title": "Best Discipline",
            "student": best_discipline.name if best_discipline else None,
            "score": best_discipline.discipline_score if best_discipline else None,
        },
        "best_behavior": {
            "title": "Best Behavior",
            "student": best_behavior.name if best_behavior else None,
            "score": best_behavior.behavior if best_behavior else None,
        },
    }
    return result, 200


@analytics_bp.get("/ai-suggestions/<student_id>")
@roles_required("college_admin", "super_admin")
def ai_suggestions(student_id):
    db = get_db()
    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    suggestions = []
    if (student.behavior or 0) < 70:
        suggestions.append("Join mentorship and behavior feedback sessions every fortnight.")
    if not suggestions:
        suggestions.append("Maintain current consistency and target leadership opportunities.")

    return {
        "student_id": student_id,
        "discipline_score": student.discipline_score or 0,
        "suggestions": suggestions,
    }, 200


@analytics_bp.get("/student-report/<student_id>")
def student_report(student_id):
    db = get_db()
    student_uuid = parse_uuid(student_id)
    if not student_uuid:
        return {"message": "Invalid student id"}, 400

    student = db.query(Student).filter(Student.id == student_uuid).first()
    if not student:
        return {"message": "Student not found"}, 404

    period = (request.args.get("period") or "weekly").strip().lower()
    if period not in ["weekly", "monthly"]:
        return {"message": "period must be weekly or monthly"}, 400

    now = datetime.now(timezone.utc)
    days = 7 if period == "weekly" else 30
    start_at = now - timedelta(days=days)

    updates_in_period = (
        db.query(DisciplineUpdate)
        .filter(
            DisciplineUpdate.student_id == student.id,
            DisciplineUpdate.status.in_(["applied", "approved"]),
            DisciplineUpdate.created_at >= start_at,
            DisciplineUpdate.created_at <= now,
        )
        .order_by(DisciplineUpdate.created_at.asc())
        .all()
    )

    baseline = (
        db.query(DisciplineUpdate)
        .filter(
            DisciplineUpdate.student_id == student.id,
            DisciplineUpdate.status.in_(["applied", "approved"]),
            DisciplineUpdate.created_at < start_at,
        )
        .order_by(DisciplineUpdate.created_at.desc())
        .first()
    )

    if updates_in_period:
        start_snapshot = (baseline.new if baseline else None) or (updates_in_period[0].previous or {})
        end_snapshot = updates_in_period[-1].new or {}
    else:
        start_snapshot = {
            "behavior": student.behavior or 0,
            "discipline_score": student.discipline_score or 0,
        }
        end_snapshot = dict(start_snapshot)

    delta_score = round(float(end_snapshot.get("discipline_score", 0)) - float(start_snapshot.get("discipline_score", 0)), 2)
    delta_behavior = round(float(end_snapshot.get("behavior", 0)) - float(start_snapshot.get("behavior", 0)), 2)

    categories = {}
    for u in updates_in_period:
        cat = u.category or "Other"
        categories[cat] = categories.get(cat, 0) + 1

    series = []
    for u in updates_in_period:
        snapshot = u.new or {}
        series.append(
            {
                "timestamp": u.applied_at or u.created_at,
                "discipline_score": snapshot.get("discipline_score"),
                "behavior": snapshot.get("behavior"),
            }
        )

    return {
        "student": {
            "id": str(student.id),
            "name": student.name,
            "roll_number": student.roll_number,
            "department": student.department,
            "year": student.year,
            "college_id": str(student.college_id) if student.college_id else None,
        },
        "period": period,
        "start_at": _iso(start_at),
        "end_at": _iso(now),
        "current": {
            "behavior": student.behavior or 0,
            "discipline_score": student.discipline_score or 0,
        },
        "summary": {
            "updates_count": len(updates_in_period),
            "categories": categories,
            "trend": _trend_label(delta_score),
        },
        "change": {
            "start": start_snapshot,
            "end": end_snapshot,
            "delta": {
                "discipline_score": delta_score,
                "behavior": delta_behavior,
            },
        },
        "series": series,
    }, 200
