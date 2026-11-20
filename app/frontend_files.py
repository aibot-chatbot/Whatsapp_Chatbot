"""Serve a page from the Astro build (web/dist) when it exists, else from legacy frontend/."""

import os

from flask import send_from_directory
from werkzeug.exceptions import NotFound
from werkzeug.security import safe_join

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
WEB_DIST_DIR = os.path.join(ROOT_DIR, "web", "dist")


def frontend_file_directory(path):
    """Return the first serving directory containing this file."""
    for directory in (WEB_DIST_DIR, FRONTEND_DIR):
        candidate = safe_join(directory, path)
        if candidate is not None and os.path.isfile(candidate):
            return directory
    return None


def send_frontend_file(path):
    """Send web/dist/<path> if built, else frontend/<path>; raises NotFound for unsafe or missing paths."""
    directory = frontend_file_directory(path)
    if directory is None:
        raise NotFound()
    return send_from_directory(directory, path)
