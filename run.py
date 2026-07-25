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
    # Start side effects only in the real serving process.
    # The werkzeug reloader parent also executes __main__ but
    # WERKZEUG_RUN_MAIN is set only in the child process.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_ngrok()

        if env_flag("WASENDER_RETRY_WORKER_ENABLED", default=True):
            start_wasender_retry_worker()

    port = int(os.getenv("FLASK_PORT", "8000"))
    
    print("\n" + "=" * 50)
    print(f" 🚀 LOCALHOST LINK: http://localhost:{port} ")
    print("=" * 50 + "\n")

    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", "8000")),
        debug=env_flag("FLASK_DEBUG", default=False),
        use_reloader=True,
    )
