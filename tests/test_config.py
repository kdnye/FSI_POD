import pytest

from app import config


@pytest.mark.parametrize(
    "value,default,expected",
    [
        ("true", False, True),
        ("1", False, True),
        (" yes ", False, True),
        ("on", False, True),
        ("false", True, False),
        ("0", True, False),
        ("no", True, False),
        (None, True, True),
        (None, False, False),
    ],
)
def test_str_to_bool_parsing(value, default, expected):
    assert config._str_to_bool(value, default=default) is expected


@pytest.mark.parametrize(
    "app_env,fsi_production,expected",
    [("prod", None, True), ("production", None, True), ("dev", "1", True), ("dev", None, False)],
)
def test_is_production_detection(monkeypatch, app_env, fsi_production, expected):
    monkeypatch.setenv("APP_ENV", app_env)
    if fsi_production is None:
        monkeypatch.delenv("FSI_PRODUCTION", raising=False)
    else:
        monkeypatch.setenv("FSI_PRODUCTION", fsi_production)

    assert config._is_production() is expected


def test_get_runtime_config_valid_local_defaults(monkeypatch):
    monkeypatch.delenv("FSI_PRODUCTION", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("REMEMBER_COOKIE_SECURE", raising=False)

    runtime_config = config.get_runtime_config()

    assert runtime_config["SECRET_KEY"] == "dev-only-change-me"
    assert runtime_config["SQLALCHEMY_DATABASE_URI"] == "postgresql+psycopg://localhost/fsi_app"
    assert runtime_config["MAX_CONTENT_LENGTH"] == 16 * 1024 * 1024
    assert runtime_config["PORT"] == 8080
    assert runtime_config["SESSION_COOKIE_SECURE"] is False
    assert runtime_config["REMEMBER_COOKIE_SECURE"] is False
    assert runtime_config["QUEUE_NAME"] == "email-queue"


def test_get_runtime_config_production_missing_secrets_raises_system_exit(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FSI_PRODUCTION", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/prod")
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.delenv("POSTMARK_SERVER_TOKEN", raising=False)
    monkeypatch.delenv("POSTMARK_FROM_EMAIL", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("PUBLIC_SERVICE_URL", raising=False)
    monkeypatch.delenv("TASK_SERVICE_ACCOUNT_EMAIL", raising=False)
    monkeypatch.delenv("TASKS_SHARED_SECRET", raising=False)

    with pytest.raises(SystemExit, match="Production configuration is invalid"):
        config.get_runtime_config()


def test_get_runtime_config_invalid_numeric_fields_rejected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("MAX_CONTENT_LENGTH_MB", "abc")

    with pytest.raises(RuntimeError, match="MAX_CONTENT_LENGTH_MB"):
        config.get_runtime_config()


def test_get_runtime_config_rejects_non_positive_numeric_fields(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "0")

    with pytest.raises(RuntimeError, match="DB_POOL_TIMEOUT"):
        config.get_runtime_config()
