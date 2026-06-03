import sys
import os
from dotenv import load_dotenv
import logging


def load_configurations(app):
    load_dotenv()
    cors_origins = os.getenv("CORS_ORIGINS", "")
    app.config["CORS_ORIGINS"] = [
        origin.strip()
        for origin in cors_origins.split(",")
        if origin.strip()
    ] or [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    app.config["ACCESS_TOKEN"] = os.getenv("ACCESS_TOKEN")
    app.config["YOUR_PHONE_NUMBER"] = os.getenv("YOUR_PHONE_NUMBER")
    app.config["APP_ID"] = os.getenv("APP_ID")
    app.config["APP_SECRET"] = os.getenv("APP_SECRET")
    app.config["RECIPIENT_WAID"] = os.getenv("RECIPIENT_WAID")
    app.config["VERSION"] = os.getenv("VERSION")
    app.config["PHONE_NUMBER_ID"] = os.getenv("PHONE_NUMBER_ID")
    app.config["VERIFY_TOKEN"] = os.getenv("VERIFY_TOKEN")


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )
