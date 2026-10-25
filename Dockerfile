# SilentSOS — production image.
# Build:  docker build -t silentsos .
# Run:    docker run -p 8001:8001 -e PUBLIC_BASE_URL=https://<host> silentsos
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8001

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY scripts ./scripts

RUN useradd -m appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

# Liveness probe: /api/health is served by the app itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD \
  python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8001')+'/api/health')"

# Seed is idempotent: on a fresh (ephemeral) database it creates the demo
# device + contacts and prints the device key to the logs once.
CMD python scripts/seed_demo.py && \
    uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8001}
