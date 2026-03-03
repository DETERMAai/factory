from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime
from database import Base

class ScanTask(Base):
tablename = "scan_tasks"