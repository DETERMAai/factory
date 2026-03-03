from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Task(Base):
    __tablename__ = "factory_tasks"
    task_id = Column(String, primary_key=True)
    status = Column(String, default="pending")
    payload = Column(JSON)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    task_id = Column(String)
    action = Column(String)
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)