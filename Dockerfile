# Production image for the chatbot SaaS.
#
# Portable on purpose: this same image runs on Cloudflare Containers, Fly.io,
# Render, Railway or any Docker host. Nothing in here is provider specific, so
# the deployment target stays a decision rather than a lock-in.
#
# Build:  docker build -t whatsapp-chatbot .
# Run:    docker run -p 8000:8000 --env-file .env whatsapp-chatbot

FROM python:3.11-slim AS base

# PyMuPDF ships manylinux wheels, so no compiler is needed. Keep it that way:
# adding a build toolchain here would triple the image size.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Dependencies first, so a code change does not reinstall the world.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "gunicorn>=21.2,<24.0"

COPY . .

# Never run as root. The app writes uploads, so the directory is created and
# handed over before the user drops privileges.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# /app/data holds uploaded PDFs and generated READMEs. Container filesystems are
# ephemeral and are NOT shared between instances, so this MUST be a mounted
# volume for a single instance, and must move to object storage (R2 or S3)
# before running more than one. See docs/DEPLOYMENT_CHECKLIST.md.
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/', timeout=4).status==200 else 1)"

# One worker by design. The app starts a background retry thread and would run
# that loop once per worker, so every extra worker means duplicate sends. Scale
# with threads until the background work moves to a queue or a separate process.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 8 --timeout 120 --access-logfile - --error-logfile - wsgi:app"]
