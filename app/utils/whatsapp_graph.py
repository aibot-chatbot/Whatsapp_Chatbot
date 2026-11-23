import os


def graph_api_version():
    return os.getenv("WHATSAPP_GRAPH_API_VERSION") or "v25.0"
