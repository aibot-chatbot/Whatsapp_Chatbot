# APP_IMAGE must be the tested release image@sha256:... containing this commit.
ARG APP_IMAGE
FROM ${APP_IMAGE}
COPY --chown=appuser:appuser analysis_worker.py /app/analysis_worker.py
ENV PORT=8081 HOST=:: PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/healthz', timeout=4)"
CMD ["python", "analysis_worker.py"]
