# LabLedger — small, dependency-light analytical platform.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LABLEDGER_HOST=0.0.0.0 \
    LABLEDGER_PORT=5000 \
    LABLEDGER_DB=/data/labledger.db \
    BRIDGE_HOST=0.0.0.0 \
    BRIDGE_PORT=5056

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite database and runtime state live on a volume so they survive restarts.
RUN mkdir -p /data
VOLUME ["/data"]

# 5000 = web UI, 5056 = instrument bridge TCP listener
EXPOSE 5000 5056

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz').status==200 else 1)"

CMD ["python", "app.py"]
