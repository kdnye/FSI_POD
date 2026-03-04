import os
from dotenv import load_dotenv
from sqlalchemy import URL

load_dotenv()

def _str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _is_production() -> bool:
    return _str_to_bool(os.getenv("FSI_PRODUCTION"), default=False) or os.getenv("APP_ENV", "").lower() in {
        "prod",
        "production",
    }

def _get_env(name: str, default: str | None = None, required_in_production: bool = False) -> str:
    value = os.getenv(name, default)
    if required_in_production and _is_production() and not value:
        raise RuntimeError(
            f"Missing required environment variable '{name}'. "
            "In Cloud Run, wire this from Secret Manager using --set-secrets."
        )
    if value is None:
        raise RuntimeError(f"Environment variable '{name}' is not set.")
    return value


def _get_max_content_length() -> int:
    raw_mb = os.getenv("MAX_CONTENT_LENGTH_MB", "16").strip()
    try:
        max_content_length_mb = int(raw_mb)
    except ValueError as exc:
        raise RuntimeError("MAX_CONTENT_LENGTH_MB must be a whole number in megabytes.") from exc

    if max_content_length_mb <= 0:
        raise RuntimeError("MAX_CONTENT_LENGTH_MB must be greater than zero.")

    return max_content_length_mb * 1024 * 1024

def get_runtime_config() -> dict:
    # Prefer fragmented DB secrets when available.
    db_user = os.getenv("DB_USER", "").strip()
    db_pass = os.getenv("DB_PASS", "").strip()
    db_name = os.getenv("DB_NAME", "").strip()
    cloud_sql_connection_name = os.getenv("CLOUD_SQL_CONNECTION_NAME", "").strip()
    has_fragmented_db_values = any([db_user, db_pass, db_name])

    if has_fragmented_db_values and not all([db_user, db_pass, db_name]):
        raise RuntimeError(
            "Incomplete database credentials. If using fragmented configuration, set DB_USER, "
            "DB_PASS, and DB_NAME together, or provide a unified DATABASE_URL."
        )

    if db_user and db_pass and db_name:
        db_kwargs = {
            "drivername": "postgresql+psycopg",
            "username": db_user,
            "password": db_pass,
            "database": db_name,
        }
        if cloud_sql_connection_name:
            db_kwargs["query"] = {"host": f"/cloudsql/{cloud_sql_connection_name}"}

        db_url_str = URL.create(**db_kwargs).render_as_string(hide_password=False)
    else:
        db_url_str = os.getenv("DATABASE_URL", "").strip()

        if _is_production() and not db_url_str:
            raise RuntimeError(
                "Missing database credentials. Please ensure DB_USER, DB_PASS, and DB_NAME "
                "are populated, or provide a unified DATABASE_URL via Secret Manager."
            )
        elif not _is_production() and not db_url_str:
            db_url_str = "postgresql+psycopg://localhost/fsi_app"

    return {
        "SECRET_KEY": _get_env("SECRET_KEY", "dev-only-change-me", required_in_production=True).strip(),
        "SQLALCHEMY_DATABASE_URI": db_url_str,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MAX_CONTENT_LENGTH": _get_max_content_length(),
        "DEBUG": _str_to_bool(os.getenv("DEBUG"), default=False),
        "PORT": int(os.getenv("PORT", "8080")),
        "SESSION_COOKIE_SECURE": _str_to_bool(os.getenv("SESSION_COOKIE_SECURE"), default=_is_production()),
        "REMEMBER_COOKIE_SECURE": _str_to_bool(os.getenv("REMEMBER_COOKIE_SECURE"), default=_is_production()),
        "LOAD_BOARD_USE_SHIPMENTS": _str_to_bool(os.getenv("LOAD_BOARD_USE_SHIPMENTS"), default=False),
        "POSTMARK_SERVER_TOKEN": _get_env("POSTMARK_SERVER_TOKEN", "").strip(),
        "POSTMARK_FROM_EMAIL": _get_env("POSTMARK_FROM_EMAIL", "").strip(),
        "GCP_PROJECT_ID": _get_env("GCP_PROJECT_ID").strip(),
        "GCP_REGION": _get_env("GCP_REGION", "us-central1").strip(),
        "QUEUE_NAME": _get_env("QUEUE_NAME", "email-queue").strip(),
        "PUBLIC_SERVICE_URL": _get_env("PUBLIC_SERVICE_URL", "", required_in_production=True).strip(),
        "TASK_SERVICE_ACCOUNT_EMAIL": _get_env("TASK_SERVICE_ACCOUNT_EMAIL", "").strip(),
    }
