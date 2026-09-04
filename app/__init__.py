from flask import Flask, request

from app.config.loader import load_settings, BASE_DIR
from app.config.db import init_mongo
from app.extensions import socketio


def create_app():
    app = Flask(__name__)

    settings = load_settings()
    app.config["SETTINGS"] = settings
    app.config["SECRET_KEY"] = settings["secrets"]["secret_key"]
    app.config["BASE_DIR"] = str(BASE_DIR)
    app.config["MAX_CONTENT_LENGTH"] = (
        settings["storage"]["max_upload_size_mb"] * 1024 * 1024
    )

    init_mongo(app, settings)
    socketio.init_app(app)
    _register_blueprints(app)
    _register_context_processors(app, settings)

    return app


def _register_blueprints(app):
    from app.blueprints.home import home_bp
    from app.blueprints.live_kitting_activities import live_kitting_activities_bp
    from app.blueprints.history import history_bp
    from app.blueprints.configuration import configuration_bp
    from app.blueprints.cv_ingest import cv_ingest_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(live_kitting_activities_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(configuration_bp)
    app.register_blueprint(cv_ingest_bp)


def _register_context_processors(app, settings):
    """
    Makes theme (read from cookie, server-side) and app name available
    to every template automatically, so base.html can set data-theme
    on <html> before first paint (no flash of wrong theme).
    """
    cookie_name = settings["theme"]["cookie_name"]
    cookie_max_age_days = settings["theme"]["cookie_max_age_days"]
    default_theme = settings["theme"]["default"]

    app_name = settings["app"]["name"]
    app_version = settings["app"]["version"]
    client_name = settings["client"]["name"]
    client_brand = settings["client"]["brand"]
    client_logo_path = settings["client"]["logo_path"]
    developer_name = settings["developer"]["name"]

    @app.context_processor
    def inject_theme_and_app_info():
        theme = request.cookies.get(cookie_name, default_theme)
        if theme not in ("dark", "light"):
            theme = default_theme
        return {
            "current_theme": theme,
            "theme_cookie_name": cookie_name,
            "theme_cookie_max_age_days": cookie_max_age_days,
            "app_name": app_name,
            "app_version": app_version,
            "client_name": client_name,
            "client_brand": client_brand,
            "client_logo_path": client_logo_path,
            "developer_name": developer_name,
        }
