from flask import Flask, g, jsonify, redirect, url_for
from flask_limiter import Limiter
from flask_migrate import Migrate
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from app.config import get_runtime_config
from app.rate_limits import DEFAULT_DAILY_LIMIT, DEFAULT_HOURLY_LIMIT

# Global extension objects
db = SQLAlchemy()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[DEFAULT_DAILY_LIMIT, DEFAULT_HOURLY_LIMIT],
)
migrate = Migrate()

def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder="../templates",
        static_folder="../static",
    )
    
    # Load configuration
    app.config.update(get_runtime_config())
    if config_overrides:
        app.config.update(config_overrides)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    # Ensure model metadata is registered for Alembic autogenerate
    import models  # noqa: F401

    # Optional: Run schema validation on startup
    from app import schema_checks
    if app.config.get("SCHEMA_FAIL_FAST_ON_STARTUP", False):
        with app.app_context():
            schema_checks.assert_required_schema()

    # --- Register Blueprints ---
    from app.blueprints.auth.routes import auth_bp
    from app.blueprints.account.routes import account_bp
    from app.blueprints.paperwork.routes import paperwork_bp
    from app.blueprints.tasks.routes import tasks_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(paperwork_bp)
    app.register_blueprint(tasks_bp, url_prefix="/tasks")

    # --- Global Routes ---

    @app.get("/readyz")
    def readiness_check():
        """Used by Cloud Run to verify the container is healthy and DB is connected."""
        with app.app_context():
            report = schema_checks.get_required_schema_report()

        if report["ok"]:
            return jsonify({"status": "ok"}), 200

        return (
            jsonify(
                {
                    "status": "error",
                    "error": report["error"],
                    "missing_columns": report["missing_columns"],
                }
            ),
            503,
        )

    @app.get("/")
    def index():
        """Entry point: Redirects to login or the POD capture screen."""
        if getattr(g, "current_user", None) is None:
            return redirect(url_for("auth.login_page"))
        return redirect(url_for("paperwork.log_pod_event"))

    return app
