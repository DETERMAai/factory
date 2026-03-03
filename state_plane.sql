-- 1. טבלת אירועים למניעת כפילויות (Idempotency)
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. טבלת המשימות הראשית
CREATE TABLE IF NOT EXISTS factory_tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, claimed, dispatched, completed, failed
    payload JSONB,
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. טבלת נעילות (Atomic Claims)
CREATE TABLE IF NOT EXISTS atomic_claims (
    task_id TEXT PRIMARY KEY REFERENCES factory_tasks(task_id),
    claim_token TEXT NOT NULL,
    claimed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- 4. לוג ביקורת (Append-Only)
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    task_id TEXT,
    action TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. אינדקסים לביצועים
CREATE INDEX IF NOT EXISTS idx_tasks_status ON factory_tasks(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_claims_expiry ON atomic_claims(expires_at);

-- 6. פונקציה לנעילת משימה (Claim) - מבטיחה שרק עובד אחד לוקח משימה
CREATE OR REPLACE FUNCTION claim_next_task(worker_token TEXT, lease_interval INTERVAL)
RETURNS TABLE(task_id TEXT) AS $$
DECLARE
    target_id TEXT;
BEGIN
    -- ניקוי נעילות שפגו תוקף (Housekeeping)
    DELETE FROM atomic_claims WHERE expires_at < CURRENT_TIMESTAMP;

    -- חיפוש משימה פנויה ונעילתה בטרנזקציה אחת
    SELECT t.task_id INTO target_id
    FROM factory_tasks t
    LEFT JOIN atomic_claims c ON t.task_id = c.task_id
    WHERE t.status = 'pending' AND c.task_id IS NULL
    ORDER BY t.priority DESC, t.created_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF target_id IS NOT NULL THEN
        INSERT INTO atomic_claims (task_id, claim_token, expires_at)
        VALUES (target_id, worker_token, CURRENT_TIMESTAMP + lease_interval);
        
        UPDATE factory_tasks SET status = 'claimed', updated_at = CURRENT_TIMESTAMP WHERE task_id = target_id;
        
        INSERT INTO audit_log (task_id, action, details) 
        VALUES (target_id, 'CLAIM', jsonb_build_object('worker', worker_token));
    END IF;

    RETURN QUERY SELECT target_id;
END;
$$ LANGUAGE plpgsql;