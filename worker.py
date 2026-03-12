import os
import json
import time
import traceback
from datetime import datetime, timezone

import psycopg2

# -------------------------
# Utilities
# -------------------------

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def http_get(url: str, timeout: float = 3.0) -> dict:
    # No curl dependency. Pure python.
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "determa-worker"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": int(getattr(resp, "status", 0) or 0), "body": body[:4000]}
    except urllib.error.HTTPError as e:
        try:
            b = e.read().decode("utf-8", errors="replace")[:4000]
        except Exception:
            b = ""
        return {"ok": False, "error": f"HTTPError {e.code}", "body": b}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# -------------------------
# Worker
# -------------------------

class Worker:
    def __init__(self):
        self.worker_id = os.getenv("WORKER_ID", "worker-1")
        self.database_url = os.environ["DATABASE_URL"]
        self.factory_api = os.getenv("FACTORY_API", "http://orchestrator:8080/health")
        self.poll_seconds = float(os.getenv("POLL_SECONDS", "2"))
        self.db_conn = psycopg2.connect(self.database_url)
        self.db_conn.autocommit = False

    def audit(self, event_type: str, payload: dict):
        with self.db_conn.cursor() as cur:
            cur.execute(
                "insert into audit_log(ts, event_type, payload) values (now(), %s, %s::jsonb)",
                (event_type, json.dumps(payload)),
            )

    def claim_task(self):
        """
        Atomically claim one pending task.
        """
        with self.db_conn.cursor() as cur:
            cur.execute(
                """
                with cte as (
                    select task_id
                    from factory_tasks
                    where status='pending'
                    order by task_id asc
                    for update skip locked
                    limit 1
                )
                update factory_tasks t
                set status='claimed', claimed_by=%s, claimed_at=now()
                from cte
                where t.task_id=cte.task_id
                returning t.task_id, t.task_name, t.payload
                """,
                (self.worker_id,),
            )
            row = cur.fetchone()
            return row

    def set_status(self, task_id: int, status: str, result: dict | None = None, error: str | None = None):
        with self.db_conn.cursor() as cur:
            cur.execute(
                """
                update factory_tasks
                set status=%s,
                    updated_at=now(),
                    result=coalesce(%s::jsonb, result),
                    error=coalesce(%s, error)
                where task_id=%s
                """,
                (status, json.dumps(result) if result is not None else None, error, task_id),
            )

    # -------------------------
    # Handlers
    # -------------------------

    def handle_self_check(self) -> dict:
        # Health endpoint
        health = http_get(self.factory_api, timeout=3.0)

        # DB queue snapshot
        db = {"ok": False}
        try:
            with self.db_conn.cursor() as cur:
                cur.execute("""
                    select
                      count(*) filter (where status='pending')   as pending,
                      count(*) filter (where status='claimed')   as claimed,
                      count(*) filter (where status='running')   as running,
                      count(*) filter (where status='completed') as completed,
                      count(*) filter (where status='failed')    as failed
                    from factory_tasks
                """)
                row = cur.fetchone()
                db = {
                    "ok": True,
                    "counts": {
                        "pending": int(row[0]),
                        "claimed": int(row[1]),
                        "running": int(row[2]),
                        "completed": int(row[3]),
                        "failed": int(row[4]),
                    },
                }
        except Exception as e:
            db = {"ok": False, "error": str(e)}

        return {
            "ts": utcnow_iso(),
            "worker_id": self.worker_id,
            "health": health,
            "db": db,
        }

    def handle_noop(self) -> dict:
        return {"ts": utcnow_iso(), "worker_id": self.worker_id, "ok": True}

    def dispatch(self, kind: str) -> dict:
        if kind == "self_check":
            return self.handle_self_check()
        if kind == "noop":
            return self.handle_noop()

        # Default: unknown kind
        return {"ts": utcnow_iso(), "worker_id": self.worker_id, "ok": False, "error": f"unknown kind: {kind}"}

    # -------------------------
    # Main loop
    # -------------------------

    def run_forever(self):
        while True:
            try:
                row = self.claim_task()
                if not row:
                    self.db_conn.commit()
                    time.sleep(self.poll_seconds)
                    continue

                task_id, task_name, payload = row
                payload = payload or {}
                kind = payload.get("kind", "noop")

                self.audit("TASK_STARTED", {"by": self.worker_id, "kind": kind, "task_id": task_id})
                self.set_status(task_id, "running")
                self.db_conn.commit()

                try:
                    result = self.dispatch(kind)
                    self.set_status(task_id, "completed", result=result)
                    self.audit("TASK_COMPLETED", {"by": self.worker_id, "kind": kind, "task_id": task_id, "result": result})
                    self.db_conn.commit()
                except Exception as e:
                    err = f"{e}\n{traceback.format_exc()}"
                    self.set_status(task_id, "failed", error=err)
                    self.audit("TASK_FAILED", {"by": self.worker_id, "kind": kind, "task_id": task_id, "error": str(e)})
                    self.db_conn.commit()

            except Exception:
                try:
                    self.db_conn.rollback()
                except Exception:
                    pass
                time.sleep(self.poll_seconds)

if __name__ == "__main__":
    Worker().run_forever()
