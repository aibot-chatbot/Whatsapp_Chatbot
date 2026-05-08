import atexit
import json
import logging
import os
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError


ngrok_process = None


def start_ngrok():
    global ngrok_process

    enabled = os.getenv("NGROK_ENABLED", "false").lower() == "true"
    if not enabled:
        logging.info("ngrok auto-start is disabled.")
        return

    ngrok_path = os.getenv("NGROK_PATH", r"C:\ngrok\ngrok.exe")
    ngrok_port = os.getenv("NGROK_PORT", "8000")
    ngrok_domain = os.getenv("NGROK_DOMAIN", "").strip()

    if not os.path.exists(ngrok_path):
        logging.warning(f"ngrok.exe not found at: {ngrok_path}")
        return

    command = [ngrok_path, "http", ngrok_port]

    if ngrok_domain:
        command.extend(["--url", ngrok_domain])

    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NO_WINDOW

    logging.info(f"Starting ngrok: {' '.join(command)}")

    ngrok_process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags
    )

    atexit.register(stop_ngrok)

    time.sleep(3)

    public_url = get_ngrok_public_url()
    if public_url:
        logging.info(f"ngrok public URL: {public_url}")
    else:
        logging.warning("ngrok started, but public URL not found yet.")


def get_ngrok_public_url():
    try:
        response = urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3)
        data = json.loads(response.read().decode("utf-8"))

        tunnels = data.get("tunnels", [])
        for tunnel in tunnels:
            public_url = tunnel.get("public_url")
            if public_url and public_url.startswith("https://"):
                return public_url

        return None

    except URLError:
        return None
    except Exception as e:
        logging.warning(f"Failed to get ngrok URL: {e}")
        return None


def stop_ngrok():
    global ngrok_process

    if ngrok_process:
        logging.info("Stopping ngrok...")
        ngrok_process.terminate()
        ngrok_process = None