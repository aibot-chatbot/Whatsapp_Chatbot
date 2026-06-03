from dotenv import load_dotenv
load_dotenv()

import os

from app import create_app
from app.utils.ngrok_runner import start_ngrok
from app.services.wasender_retry_service import start_wasender_retry_worker

app = create_app()


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes")


if __name__ == "__main__":
    start_ngrok()

    if env_flag("WASENDER_RETRY_WORKER_ENABLED", default=True):
        start_wasender_retry_worker()

    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", "8000")),
        debug=env_flag("FLASK_DEBUG", default=False),
        use_reloader=False,
    )
