FROM python:3.11-slim

WORKDIR /app

# GitPython (used for local git ops and GitHub-URL cloning) shells out to a
# real `git` binary — python:3.11-slim does not include one.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app
COPY demo-repository /demo-repository

ENV PYTHONPATH=/app
EXPOSE 8000

# Non-root runtime user. /data is where the compose volume is mounted (see
# docker-compose.yml) — create it here, owned by the app user, so a fresh
# named volume inherits the right ownership on first mount.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data /demo-repository
USER appuser

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
