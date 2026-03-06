from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
import models, database, uuid

app = FastAPI(title="DETERMA Orchestrator")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}


@app.post("/webhook/ingress")
async def ingress(payload: dict, db: Session = Depends(database.get_db)):
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    new_task = models.Task(task_id=task_id, payload=payload, status="pending")
    db.add(new_task)

    log = models.AuditLog(task_id=task_id, action="INGRESS_RECEIVED", details=payload)
    db.add(log)

    db.commit()
    return {"status": "accepted", "task_id": task_id}


@app.post("/dispatcher/wakeup")
async def dispatch(db: Session = Depends(database.get_db)):
    runner = "main-orchestrator"
    task_id = database.claim_task(db, runner)

    if not task_id:
        log = models.AuditLog(
            task_id="system",
            action="DISPATCH_IDLE",
            details={"runner": runner},
        )
        db.add(log)
        db.commit()
        return {"status": "idle", "message": "No pending tasks"}

    log = models.AuditLog(
        task_id=task_id,
        action="TASK_DISPATCHED",
        details={"runner": runner},
    )
    db.add(log)
    db.commit()

    return {"status": "dispatched", "task_id": task_id}
