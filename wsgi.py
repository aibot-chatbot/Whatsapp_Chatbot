"""
WSGI entry point for production deployment.

Usage:
    gunicorn wsgi:app
    waitress-serve wsgi:app

For local development, use run.py instead.
"""

from app import create_app

app = create_app()
