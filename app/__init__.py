from flask import Flask
import os
from flask_cors import CORS
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint
from app.routes.chat_routes import chat_blueprint
from app.routes.settings_routes import settings_blueprint
from app.routes.knowledge_routes import knowledge_blueprint
from app.routes.profile_routes import profile_blueprint
from app.routes.match_routes import match_blueprint
from app.routes.testbot_routes import testbot_blueprint
from app.routes.analytics_routes import analytics_blueprint
from app.routes.auth_routes import auth_bp
from app.routes.bot_routes import bot_blueprint
from app.routes.conversation_routes import conversation_blueprint

def create_app():
    # 1. Correctly locate the project root (up one level from 'app' folder)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        
    # 2. Define both the template and the static folder paths
    app = Flask(__name__, 
                template_folder=os.path.join(root_dir, 'frontend'),
                static_folder=os.path.join(root_dir, 'frontend', 'static')) # Added this!

    CORS(app, resources={r"/*": {"origins": "*"}})

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()

    # Register blueprints
    app.register_blueprint(webhook_blueprint)
    app.register_blueprint(chat_blueprint)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(knowledge_blueprint)
    app.register_blueprint(profile_blueprint)
    app.register_blueprint(match_blueprint)
    app.register_blueprint(testbot_blueprint)
    app.register_blueprint(analytics_blueprint)
    app.register_blueprint(auth_bp)
    app.register_blueprint(bot_blueprint)
    app.register_blueprint(conversation_blueprint)

    return app