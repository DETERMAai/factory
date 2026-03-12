from fastapi import FastAPI, Depends, Request, HTTPException
from sqlalchemy.orm import Session
import os
import json

import models
import database
from github_webhook import (
    verify_github_signature_256,
    should_process_event,
    extract_delivery_id,
)

app = FastAPI(title="DETERMA Orchestrator")


@app.get("/health")
async def health():
    return {"ok": True}


def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise HTTPException(status_code=500, detail=f"Missing {name}")
    return val


@app.post("/webhook/ingress")
async def ingress(request: Request, db: Session = Depends(database.get_db)):
    raw = await request.body()

    # 0) Verify GitHub signature
    secret = require_env("GITHUB_WEBHOOK_SECRET")
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature_256(secret=secret, body=raw, signature_header=sig):
        raise HTTPException(status_code=401, detail="Bad signature")

    # 1) Delivery id
    delivery_id = extract_delivery_id(dict(request.headers))
    if not delivery_id:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery")

    # 2) Do not process same delivery twice
    if database.is_delivery_processed(db, delivery_id):
        return {
            "status": "ignored",
            "reason": "duplicate_delivery",
            "delivery_id": delivery_id,
        }

    # 3) Parse payload
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 4) Fail-closed event filter
    event_name = request.headers.get("X-GitHub-Event")
    if not should_process_event(event_name, payload):
        db.add(models.ProcessedEvent(delivery_id=delivery_id, task_id=f"ignored-{delivery_id}"))
        db.commit()
        return {
            "status": "ignored",
            "reason": "event_filtered",
            "delivery_id": delivery_id,
            "event": event_name,
        }

    # 5) Deterministic task id
    task_id = f"gh-{delivery_id}"

    # 6) Create task
    new_task = models.FactoryTask(
        task_id=task_id,
        payload=payload,
        status="pending",
    )
    db.add(new_task)

    # 7) Audit log
    db.add(
        models.AuditLog(
            task_id=task_id,
            action="INGRESS_RECEIVED",
            details={
                "delivery_id": delivery_id,
                "event": event_name,
                "ref": payload.get("ref"),
                "sender": ((payload.get("sender") or {}).get("login")),
            },
        )
    )

    # 8) Mark delivery as processed
    db.add(models.ProcessedEvent(delivery_id=delivery_id, task_id=task_id))

    db.commit()
    return {
        "status": "accepted",
        "task_id": task_id,
        "delivery_id": delivery_id,
        "event": event_name,
    }
