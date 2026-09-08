"""Flask authentication service. Run from BE with: flask --app app run --port 8000."""

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from auth import storage
from auth.routes import auth_blueprint


DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "https://spoti.ingyuc.click",
]


def create_app(test_config=None):
    load_dotenv(Path(__file__).with_name(".env"))
    app = Flask(__name__)
    configured_origins = os.getenv("CORS_ALLOWED_ORIGINS")
    app.config.from_mapping(
        CORS_ALLOWED_ORIGINS=(
            [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
            if configured_origins is not None
            else DEFAULT_CORS_ORIGINS
        ),
    )
    if test_config:
        app.config.update(test_config)

    CORS(
        app,
        resources={r"/auth/*": {"origins": app.config["CORS_ALLOWED_ORIGINS"]}},
        methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        supports_credentials=False,
    )
    app.register_blueprint(auth_blueprint)

    @app.errorhandler(storage.StorageUnavailable)
    def storage_unavailable(error):
        app.logger.warning("Authentication storage unavailable: %s", error)
        return jsonify(detail=str(error)), 503

    @app.errorhandler(storage.UsernameAlreadyExists)
    def username_already_exists(_error):
        return jsonify(detail="username already exists"), 409

    @app.get("/")
    def health():
        return jsonify(ok=True)

    if not app.config["TESTING"]:
        try:
            storage.init_auth_storage()
            if storage.is_configured():
                storage.delete_expired_sessions()
        except storage.StorageUnavailable as error:
            # Keep the process available so requests receive an explicit JSON 503.
            app.logger.warning("Authentication storage initialization skipped: %s", error)

    return app
