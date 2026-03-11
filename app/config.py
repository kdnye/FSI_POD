import os
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError, computed_field, field_validator
from sqlalchemy import URL

load_dotenv()


def _str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    APP_ENV: str = "local"
    FSI_PRODUCTION: bool = False

    SECRET_KEY: str = "dev-only-change-me"
    DATABASE_URL: str = ""
    PORT: int = 8080
    DEBUG: bool = False

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    MAX_CONTENT_LENGTH_MB: int = 16

    SESSION_COOKIE_SECURE: bool | None = None
    REMEMBER_COOKIE_SECURE: bool | None = None
    LOAD_BOARD_USE_SHIPMENTS: bool = False
    SCHEMA_FAIL_FAST_ON_STARTUP: bool | None = None

    DB_USER: str = ""
    DB_PASS: str = ""
    DB_NAME: str = ""
    CLOUD_SQL_CONNECTION_NAME: str = ""

    POSTMARK_SERVER_TOKEN: str = ""
    POSTMARK_FROM_EMAIL: str = ""
    GCP_PROJECT_ID: str = ""
    GCP_REGION: str = "us-central1"

    EMAIL_QUEUE_NAME: str = "email-queue"
    PUBLIC_SERVICE_URL: str = ""
    TASK_SERVICE_ACCOUNT_EMAIL: str = ""
    TASKS_EXPECTED_QUEUE_NAME: str | None = None
    TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL: str | None = None
    TASKS_EXPECTED_AUDIENCE: str | None = None
    TASKS_SHARED_SECRET: str = ""

    @computed_field(return_type=bool)
    @property
    def is_production(self) -> bool:
        return self.FSI_PRODUCTION or self.APP_ENV.lower() in {"prod", "production"}

    @field_validator(
        "PORT",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "MAX_CONTENT_LENGTH_MB",
        mode="after",
    )
    @classmethod
    def _validate_positive_ints(cls, value: int, info):
        if value <= 0:
            raise ValueError(f"{info.field_name} must be greater than zero.")
        return value

    def apply_derived_defaults(self) -> None:
        if self.SESSION_COOKIE_SECURE is None:
            self.SESSION_COOKIE_SECURE = self.is_production
        if self.REMEMBER_COOKIE_SECURE is None:
            self.REMEMBER_COOKIE_SECURE = self.is_production
        if self.SCHEMA_FAIL_FAST_ON_STARTUP is None:
            self.SCHEMA_FAIL_FAST_ON_STARTUP = self.is_production

        if not self.TASKS_EXPECTED_QUEUE_NAME:
            self.TASKS_EXPECTED_QUEUE_NAME = self.EMAIL_QUEUE_NAME
        if not self.TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL:
            self.TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL = self.TASK_SERVICE_ACCOUNT_EMAIL
        if not self.TASKS_EXPECTED_AUDIENCE and self.PUBLIC_SERVICE_URL:
            self.TASKS_EXPECTED_AUDIENCE = (
                f"{self.PUBLIC_SERVICE_URL.rstrip('/')}/tasks/api/tasks/send-email"
            )

    def validate_cross_field_constraints(self) -> None:
        has_fragmented_db_values = any([self.DB_USER, self.DB_PASS, self.DB_NAME])
        if has_fragmented_db_values and not all([self.DB_USER, self.DB_PASS, self.DB_NAME]):
            raise RuntimeError(
                "Incomplete database credentials. If using fragmented configuration, set DB_USER, "
                "DB_PASS, and DB_NAME together, or provide a unified DATABASE_URL."
            )

    def database_uri(self) -> str:
        if self.DB_USER and self.DB_PASS and self.DB_NAME:
            db_kwargs: dict[str, Any] = {
                "drivername": "postgresql+psycopg",
                "username": self.DB_USER,
                "password": self.DB_PASS,
                "database": self.DB_NAME,
            }
            if self.CLOUD_SQL_CONNECTION_NAME:
                db_kwargs["query"] = {"host": f"/cloudsql/{self.CLOUD_SQL_CONNECTION_NAME}"}
            return URL.create(**db_kwargs).render_as_string(hide_password=False)

        if self.DATABASE_URL:
            return self.DATABASE_URL

        if self.is_production:
            raise RuntimeError(
                "Missing database credentials. Please ensure DB_USER, DB_PASS, and DB_NAME "
                "are populated, or provide a unified DATABASE_URL via Secret Manager."
            )

        return "postgresql+psycopg://localhost/fsi_app"

    def enforce_production_requirements(self) -> None:
        if not self.is_production:
            return

        required_values = {
            "SECRET_KEY": self.SECRET_KEY,
            "POSTMARK_SERVER_TOKEN": self.POSTMARK_SERVER_TOKEN,
            "POSTMARK_FROM_EMAIL": self.POSTMARK_FROM_EMAIL,
            "GCP_PROJECT_ID": self.GCP_PROJECT_ID,
            "PUBLIC_SERVICE_URL": self.PUBLIC_SERVICE_URL,
            "TASK_SERVICE_ACCOUNT_EMAIL": self.TASK_SERVICE_ACCOUNT_EMAIL,
            "TASKS_EXPECTED_QUEUE_NAME": self.TASKS_EXPECTED_QUEUE_NAME,
            "TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL": self.TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL,
            "TASKS_EXPECTED_AUDIENCE": self.TASKS_EXPECTED_AUDIENCE,
            "TASKS_SHARED_SECRET": self.TASKS_SHARED_SECRET,
        }
        missing_keys = [key for key, value in required_values.items() if not str(value or "").strip()]
        if missing_keys:
            raise SystemExit(
                "Production configuration is invalid. Set the following environment variables "
                f"(Secret Manager recommended): {', '.join(missing_keys)}"
            )


def _is_production() -> bool:
    try:
        settings = RuntimeSettings.model_validate(dict(os.environ))
    except ValidationError:
        return False
    return settings.is_production


def _format_validation_error(exc: ValidationError) -> str:
    details: list[str] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error.get("loc", [])) or "<root>"
        details.append(f"{field}: {error.get('msg', 'invalid value')}")
    return "Invalid environment configuration: " + "; ".join(details)


def get_runtime_config() -> dict:
    try:
        settings = RuntimeSettings.model_validate(dict(os.environ))
    except ValidationError as exc:
        raise RuntimeError(_format_validation_error(exc)) from exc

    settings.apply_derived_defaults()
    settings.validate_cross_field_constraints()
    settings.enforce_production_requirements()

    return {
        "SECRET_KEY": settings.SECRET_KEY,
        "SQLALCHEMY_DATABASE_URI": settings.database_uri(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
        },
        "MAX_CONTENT_LENGTH": settings.MAX_CONTENT_LENGTH_MB * 1024 * 1024,
        "DEBUG": settings.DEBUG,
        "PORT": settings.PORT,
        "SESSION_COOKIE_SECURE": settings.SESSION_COOKIE_SECURE,
        "REMEMBER_COOKIE_SECURE": settings.REMEMBER_COOKIE_SECURE,
        "LOAD_BOARD_USE_SHIPMENTS": settings.LOAD_BOARD_USE_SHIPMENTS,
        "POSTMARK_SERVER_TOKEN": settings.POSTMARK_SERVER_TOKEN,
        "POSTMARK_FROM_EMAIL": settings.POSTMARK_FROM_EMAIL,
        "GCP_PROJECT_ID": settings.GCP_PROJECT_ID,
        "GCP_REGION": settings.GCP_REGION,
        "EMAIL_QUEUE_NAME": settings.EMAIL_QUEUE_NAME,
        "QUEUE_NAME": settings.EMAIL_QUEUE_NAME,
        "PUBLIC_SERVICE_URL": settings.PUBLIC_SERVICE_URL,
        "TASK_SERVICE_ACCOUNT_EMAIL": settings.TASK_SERVICE_ACCOUNT_EMAIL,
        "TASKS_EXPECTED_QUEUE_NAME": settings.TASKS_EXPECTED_QUEUE_NAME,
        "TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL": settings.TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL,
        "TASKS_EXPECTED_AUDIENCE": settings.TASKS_EXPECTED_AUDIENCE,
        "TASKS_SHARED_SECRET": settings.TASKS_SHARED_SECRET,
        "SCHEMA_FAIL_FAST_ON_STARTUP": settings.SCHEMA_FAIL_FAST_ON_STARTUP,
    }
