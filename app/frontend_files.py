"""Serve a page from the Astro build (web/dist) when it exists, else from legacy frontend/."""

import os

from flask import send_from_directory
from werkzeug.security import safe_join

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
WEB_DIST_DIR = os.path.join(ROOT_DIR, "web", "dist")


def send_frontend_file(path):
    """Send web/dist/<path> if built, else frontend/<path>; raises NotFound for unsafe or missing paths."""
    # safe_join returns None for "..", absolute and drive paths, so neither root can be escaped.
    built = safe_join(WEB_DIST_DIR, path)
    if built is not None and os.path.isfile(built):
        return send_from_directory(WEB_DIST_DIR, path)
    return send_from_directory(FRONTEND_DIR, path)
