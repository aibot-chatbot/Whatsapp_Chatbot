from dotenv import load_dotenv
load_dotenv()

import os

from app import create_app
from app.services.wasender_retry_service import start_wasender_retry_worker

app = create_app()


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes")


if __name__ == "__main__":
    if env_flag("WASENDER_RETRY_WORKER_ENABLED", default=True):
        start_wasender_retry_worker()

    port = int(os.getenv("FLASK_PORT", "8000"))
    
    print("\n" + "=" * 50)
    print(f" 🚀 LOCALHOST LINK: http://localhost:{port} ")
    print("=" * 50 + "\n")

    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "8000")),
        debug=env_flag("FLASK_DEBUG", default=False),
        use_reloader=False,
    )
