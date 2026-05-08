from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.utils.ngrok_runner import start_ngrok

app = create_app()

if __name__ == "__main__":
    start_ngrok()
    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=False)