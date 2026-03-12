FROM python:3.11-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PYTHONPATH=/app

# Auto-detect the module that contains: app = FastAPI(...)
RUN python - <<'PY'
import os, re, sys
root = "/app"
candidates = []
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in ("venv", "__pycache__", ".git")]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        try:
            s = open(p, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if "FastAPI" in s and re.search(r"^\s*app\s*=\s*FastAPI\s*\(", s, re.M):
            rel = os.path.relpath(p, root).replace(os.sep, ".")
            mod = rel[:-3]
            candidates.append(mod)
if not candidates:
    print("ERROR: could not find 'app = FastAPI(' in /app", file=sys.stderr)
    sys.exit(1)
picked = sorted(candidates)[0]
open("/app/_uvicorn_target.txt", "w").write(picked + ":app\n")
print("Picked uvicorn target:", picked + ":app")
PY

CMD ["sh", "-lc", "uvicorn \"$(cat /app/_uvicorn_target.txt)\" --host 0.0.0.0 --port 8080"]
