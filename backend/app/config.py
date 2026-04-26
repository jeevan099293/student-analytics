import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/student_leaderboard")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-secret")
    JWT_ACCESS_TOKEN_EXPIRES = 60 * 60 * 12
    SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "superadmin@example.com")
    SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "SuperAdmin@123")
    PORT = int(os.getenv("PORT", "5000"))

    # Discipline update governance
    # Score is typically 0-100 (weighted from attendance/behavior/participation).
    MAJOR_SCORE_DELTA_THRESHOLD = float(os.getenv("MAJOR_SCORE_DELTA_THRESHOLD", "15"))
    SUSPICIOUS_SCORE_DELTA_THRESHOLD = float(os.getenv("SUSPICIOUS_SCORE_DELTA_THRESHOLD", "25"))
    MAJOR_METRIC_DELTA_THRESHOLD = float(os.getenv("MAJOR_METRIC_DELTA_THRESHOLD", "30"))
    SUSPICIOUS_METRIC_DELTA_THRESHOLD = float(os.getenv("SUSPICIOUS_METRIC_DELTA_THRESHOLD", "45"))
