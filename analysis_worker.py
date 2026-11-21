"""Dedicated process: python analysis_worker.py. Never imports wsgi/create_app."""
import json
import logging
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    if os.getenv("ANALYSIS_WORKER_ENABLED", "false").lower() != "true":
        raise SystemExit("ANALYSIS_WORKER_ENABLED must be true")
    # Fail closed against accidental inherited Flask scheduler settings.
    for name in ("BILLING_SCHEDULER_ENABLED", "INGEST_QUEUE_ENABLED"):
        os.environ[name] = "false"
    from app.services.analysis_worker_service import run_once

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stop = threading.Event()
    health = {"last_poll": 0.0, "poll_ok": False}

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path == "/healthz" and health["poll_ok"] and time.monotonic() - health["last_poll"] < 900
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok" if ok else "degraded"}).encode())

        def log_message(self, *_args):
            pass

    host = os.getenv("HOST", "0.0.0.0")
    class HealthServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    server = HealthServer((host, int(os.getenv("PORT", "8081"))), Health)
    threading.Thread(target=server.serve_forever, daemon=True, name="analysis-health").start()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop.set())
    try:
        while not stop.is_set():
            try:
                # Separate ownership with one processor; neither kind starves the other.
                run_once(worker_kind="agent_report")
                run_once(worker_kind="business_observation")
                if os.getenv("TUITION_REMINDERS_ENABLED", "false").lower() == "true":
                    run_once(worker_kind="tuition_reminder")
                health.update(last_poll=time.monotonic(), poll_ok=True)
            except Exception:
                health.update(last_poll=time.monotonic(), poll_ok=False)
                logging.error("analysis_poll_failed")
            stop.wait(5)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
