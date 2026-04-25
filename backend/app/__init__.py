from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from pymongo import ASCENDING, DESCENDING

from .config import Config
from .routes.admins_routes import admins_bp
from .routes.analytics_routes import analytics_bp
from .routes.auth_routes import auth_bp
from .routes.colleges_routes import colleges_bp
from .routes.discipline_routes import discipline_bp
from .routes.leaderboard_routes import leaderboard_bp
from .routes.notifications_routes import notifications_bp
from .routes.students_routes import students_bp


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parents[2]
    static_dir = base_dir / "backend" / "static"
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="/")
    app.config.from_object(Config)

    CORS(app)
    JWTManager(app)

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(colleges_bp, url_prefix="/api/colleges")
    app.register_blueprint(admins_bp, url_prefix="/api/admins")
    app.register_blueprint(students_bp, url_prefix="/api/students")
    app.register_blueprint(discipline_bp, url_prefix="/api")
    app.register_blueprint(leaderboard_bp, url_prefix="/api/leaderboard")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")

    with app.app_context():
        from .db import get_db

        db = get_db()
        db.students.create_index([("college_id", ASCENDING), ("roll_number", ASCENDING)], unique=True)
        db.students.create_index([("discipline_score", DESCENDING)])
        db.students.create_index([("college_id", ASCENDING), ("department", ASCENDING)])
        db.students.create_index([("year", ASCENDING)])
        db.students.create_index([("name", ASCENDING)])
        db.admins.create_index([("email", ASCENDING)], unique=True)
        db.colleges.create_index([("name", ASCENDING)], unique=True)
        db.notifications.create_index([("college_id", ASCENDING), ("is_read", ASCENDING)])
        db.notifications.create_index([("created_at", DESCENDING)])

        db.discipline_updates.create_index([("student_id", ASCENDING), ("created_at", DESCENDING)])
        db.discipline_updates.create_index([("college_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)])
        db.discipline_updates.create_index([("status", ASCENDING), ("created_at", DESCENDING)])

    @app.get("/api/health")
    def health_check():
        return {"status": "ok", "service": "student-leaderboard-api"}, 200

    @app.get("/")
    def serve_index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/<path:path>")
    def serve_static(path: str):
        return send_from_directory(app.static_folder, path)

    return app
