import logging

from flask import Flask, g, has_request_context, jsonify, redirect, request, url_for
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

TRACE_HEADER_NAME = "X-Cloud-Trace-Context"
DEFAULT_TRACE_ID = "missing-trace-id"


def _extract_trace_id(trace_header: str | None) -> str:
    if not trace_header:
        return DEFAULT_TRACE_ID

    trace_id = trace_header.split("/", 1)[0].strip()
    return trace_id or DEFAULT_TRACE_ID


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = DEFAULT_TRACE_ID
        record.request_id = "-"
        record.route = "-"
        record.method = "-"
        record.status = "-"

        if has_request_context():
            record.trace_id = getattr(g, "trace_id", DEFAULT_TRACE_ID)
            record.request_id = request.headers.get("X-Request-Id", "-")
            record.route = getattr(request.url_rule, "rule", request.path)
            record.method = request.method
            status_code = getattr(g, "response_status_code", None)
            record.status = str(status_code) if status_code is not None else "-"

        return True


def _configure_logging(app: Flask) -> None:
    request_context_filter = RequestContextFilter()
    formatter = logging.Formatter(
        '{"severity":"%(levelname)s","message":"%(message)s","trace_id":"%(trace_id)s",'
        '"request_id":"%(request_id)s","route":"%(route)s","method":"%(method)s",'
        '"status":"%(status)s"}'
    )

    app.logger.addFilter(request_context_filter)
    for handler in app.logger.handlers:
        handler.addFilter(request_context_filter)
        handler.setFormatter(formatter)

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

    _configure_logging(app)

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

    @app.before_request
    def bind_request_logging_context() -> None:
        g.trace_id = _extract_trace_id(request.headers.get(TRACE_HEADER_NAME))
        g.response_status_code = None

    @app.after_request
    def store_response_status(response):
        g.response_status_code = response.status_code
        return response

    @app.teardown_request
    def log_request_completion(exc: Exception | None) -> None:
        if exc is not None:
            g.response_status_code = 500
        app.logger.info("request.completed")

    @app.get("/readyz")
    def readiness_check():
        """Used by Cloud Run to verify the container is healthy and DB is connected."""
        with app.app_context():
            report = schema_checks.get_readiness_report()

        if report["ok"]:
            return jsonify({"status": "ok", "components": report["components"]}), 200

        return (
            jsonify(
                {
                    "status": "error",
                    "errors": report["errors"],
                    "components": report["components"],
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
