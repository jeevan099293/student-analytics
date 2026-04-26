from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import declarative_base


Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc)


class College(Base):
    __tablename__ = "colleges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), unique=True, nullable=False)
    location = Column(String(200), nullable=False)
    admin_ids = Column(ARRAY(UUID(as_uuid=True)), default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    college_id = Column(UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("college_id", "roll_number", name="uq_students_college_roll"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(200), nullable=False, index=True)
    roll_number = Column(String(100), nullable=False)
    college_id = Column(UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True)
    department = Column(String(200), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    bio = Column(Text, nullable=True)
    contact_email = Column(String(200), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    photo_url = Column(Text, nullable=True)

    attendance = Column(Float, nullable=False, default=0)
    behavior = Column(Float, nullable=False, default=0)
    participation = Column(Float, nullable=False, default=0)
    discipline_score = Column(Float, nullable=False, default=0, index=True)

    rank_global = Column(Integer, nullable=True)
    rank_college = Column(Integer, nullable=True)
    rank_department = Column(Integer, nullable=True)

    achievements = Column(JSONB, nullable=False, default=list)
    history = Column(JSONB, nullable=False, default=list)

    approved = Column(Boolean, nullable=False, default=False)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class DisciplineUpdate(Base):
    __tablename__ = "discipline_updates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True)
    college_id = Column(UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=False, index=True)
    department = Column(String(200), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    created_by = Column(JSONB, nullable=False, default=dict)

    category = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)
    details = Column(Text, nullable=True)

    previous = Column(JSONB, nullable=False, default=dict)
    new = Column(JSONB, nullable=False, default=dict)
    delta = Column(JSONB, nullable=False, default=dict)

    new_behavior = Column(Float, nullable=True)
    new_discipline_score = Column(Float, nullable=True)
    delta_behavior = Column(Float, nullable=True)
    delta_discipline_score = Column(Float, nullable=True)

    requires_approval = Column(Boolean, nullable=False, default=False)
    status = Column(String(50), nullable=False, default="applied")
    reviewed_by = Column(JSONB, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    suspicious = Column(Boolean, nullable=False, default=False)
    suspicious_flags = Column(JSONB, nullable=False, default=list)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=True, index=True)
    college_id = Column(UUID(as_uuid=True), ForeignKey("colleges.id"), nullable=True, index=True)
    message = Column(Text, nullable=False)
    event_type = Column(String(100), nullable=False, default="score_update")
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
