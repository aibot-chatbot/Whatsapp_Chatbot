from dotenv import load_dotenv
load_dotenv()

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "8000"))
    
    print("\n" + "=" * 50)
    print(f" [START] LOCALHOST LINK: http://localhost:{port} ")
    print("=" * 50 + "\n")

    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", "8000")),
        debug=env_flag("FLASK_DEBUG", default=False),
        use_reloader=False,
    )
