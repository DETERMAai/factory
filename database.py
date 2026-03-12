# /opt/determa/app/database.py

from __future__ import annotations

import os
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_delivery_processed(db: Session, delivery_id: str) -> bool:
    # Uses processed_events table
    q = text("SELECT 1 FROM processed_events WHERE delivery_id = :delivery_id LIMIT 1")
    return db.execute(q, {"delivery_id": delivery_id}).first() is not None


def claim_task(db: Session, claimer: str) -> Optional[str]:
    """
    Atomically claim the next pending task.
    Uses a DB transaction + FOR UPDATE SKIP LOCKED.
    Also records in atomic_claims and audit_log.
    """

    with db.begin():
        # 1) Lock one pending task row
        row = db.execute(
            text(
                """
                SELECT task_id
                FROM factory_tasks
                WHERE status = 'pending'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
        ).first()

        if not row:
            return None

        task_id = row[0]

        # 2) Mark task as claimed
        db.execute(
            text(
                """
                UPDATE factory_tasks
                SET status = 'claimed',
                    claimed_by = :claimer,
                    claimed_at = NOW()
                WHERE task_id = :task_id
                """
            ),
            {"claimer": claimer, "task_id": task_id},
        )

        # 3) Write atomic claim record (idempotent on task_id)
        db.execute(
            text(
                """
                INSERT INTO atomic_claims (task_id, claimed_by, claimed_at)
                VALUES (:task_id, :claimer, NOW())
                ON CONFLICT (task_id) DO NOTHING
                """
            ),
            {"task_id": task_id, "claimer": claimer},
        )

        # 4) Audit
        db.execute(
            text(
                """
                INSERT INTO audit_log (task_id, action, details, created_at)
                VALUES (:task_id, 'TASK_CLAIMED', CAST(:details AS jsonb), NOW())
                """
            ),
            {"task_id": task_id, "details": '{"claimer":"' + claimer + '"}'},
        )

    return task_id