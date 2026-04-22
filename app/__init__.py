from flask import Flask
from flask_cors import CORS
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint
from app.routes.chat_routes import chat_blueprint
from app.routes.settings_routes import settings_blueprint
from app.routes.knowledge_routes import knowledge_blueprint
from app.routes.profile_routes import profile_blueprint
from app.routes.match_routes import match_blueprint

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
    app.register_blueprint(knowledge_blueprint)
    app.register_blueprint(profile_blueprint)
    app.register_blueprint(match_blueprint)

    return app
