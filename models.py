# /opt/determa/app/models.py

from __future__ import annotations

from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from database import Base


class FactoryTask(Base):
    __tablename__ = "factory_tasks"

    task_id = Column(String, primary_key=True)
    status = Column(String, nullable=False, index=True)
    payload = Column(JSONB, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    claimed_by = Column(String, nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    details = Column(JSONB, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AtomicClaim(Base):
    __tablename__ = "atomic_claims"

    # If your table uses a different PK, adjust accordingly.
    # This version assumes task_id is unique for claims.
    task_id = Column(String, primary_key=True)
    claimed_by = Column(String, nullable=False)
    claimed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    delivery_id = Column(String, primary_key=True)
    task_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)