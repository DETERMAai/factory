import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(os.getenv("DATABASE_URL"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# פונקציה לנעילת המשימה הבאה בטור
def claim_task(db, worker_name: str):
    # קריאה לפונקציית ה-SQL שכתבנו ב-Step 1
    sql = text("SELECT * FROM claim_next_task(:worker, '10 minutes')")
    result = db.execute(sql, {"worker": worker_name}).fetchone()
    return result[0] if result else None