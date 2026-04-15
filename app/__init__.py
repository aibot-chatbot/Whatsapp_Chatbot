from flask import Flask
from flask_cors import CORS
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint
from app.routes.chat_routes import chat_blueprint
from app.routes.settings_routes import settings_blueprint

def create_app():
    app = Flask(__name__)
    CORS(app)

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()

    # Import and register blueprints, if any
    app.register_blueprint(webhook_blueprint)
    app.register_blueprint(chat_blueprint)
    app.register_blueprint(settings_blueprint)

    return app
