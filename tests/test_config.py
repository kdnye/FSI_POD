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


@pytest.mark.parametrize("app_env,fsi_production,expected", [("prod", None, True), ("production", None, True), ("dev", "1", True), ("dev", None, False)])
def test_is_production_detection(monkeypatch, app_env, fsi_production, expected):
    monkeypatch.setenv("APP_ENV", app_env)
    if fsi_production is None:
        monkeypatch.delenv("FSI_PRODUCTION", raising=False)
    else:
        monkeypatch.setenv("FSI_PRODUCTION", fsi_production)

    assert config._is_production() is expected


def test_get_runtime_config_defaults_for_local(monkeypatch):
    monkeypatch.delenv("FSI_PRODUCTION", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("REMEMBER_COOKIE_SECURE", raising=False)

    runtime_config = config.get_runtime_config()

    assert runtime_config["SECRET_KEY"] == "dev-only-change-me"
    assert runtime_config["SQLALCHEMY_DATABASE_URI"] == "postgresql+psycopg://localhost/fsi_app"
    assert runtime_config["DEBUG"] is False
    assert runtime_config["SESSION_COOKIE_SECURE"] is False
    assert runtime_config["REMEMBER_COOKIE_SECURE"] is False


def test_get_runtime_config_production_requires_secret_values(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/prod")

    with pytest.raises(RuntimeError, match="Missing required environment variable 'SECRET_KEY'"):
        config.get_runtime_config()


def test_get_runtime_config_accepts_explicit_secure_cookie_overrides(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/prod")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("REMEMBER_COOKIE_SECURE", "0")

    runtime_config = config.get_runtime_config()

    assert runtime_config["SESSION_COOKIE_SECURE"] is False
    assert runtime_config["REMEMBER_COOKIE_SECURE"] is False


def test_get_runtime_config_accepts_database_url_without_fragmented_secrets(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/prod")
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    runtime_config = config.get_runtime_config()

    assert runtime_config["SQLALCHEMY_DATABASE_URI"] == "postgresql+psycopg://db/prod"


def test_get_runtime_config_rejects_partial_fragmented_db_credentials(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret")
    monkeypatch.setenv("DB_USER", "fsi")
    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    with pytest.raises(RuntimeError, match="Incomplete database credentials"):
        config.get_runtime_config()
