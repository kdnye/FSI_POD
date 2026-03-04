import os

import pytest

from app import create_app, db
from models import Role, User

os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("PUBLIC_SERVICE_URL", "https://example.run.app")
os.environ.setdefault("TASK_SERVICE_ACCOUNT_EMAIL", "tasks-invoker@example.iam.gserviceaccount.com")
os.environ.setdefault("POSTMARK_SERVER_TOKEN", "test-postmark-token")
os.environ.setdefault("POSTMARK_FROM_EMAIL", "notifications@example.com")
os.environ.setdefault("TASKS_SHARED_SECRET", "test-task-secret")
os.environ.setdefault("TASKS_EXPECTED_QUEUE_NAME", "email-queue")
os.environ.setdefault("TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL", "tasks-invoker@example.iam.gserviceaccount.com")
os.environ.setdefault("TASKS_EXPECTED_AUDIENCE", "https://example.run.app/api/tasks/send-email")


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "GCP_PROJECT_ID": "test-project",
            "PUBLIC_SERVICE_URL": "https://example.run.app",
            "TASK_SERVICE_ACCOUNT_EMAIL": "tasks-invoker@example.iam.gserviceaccount.com",
            "TASKS_SHARED_SECRET": "test-task-secret",
            "TASKS_EXPECTED_QUEUE_NAME": "email-queue",
            "TASKS_EXPECTED_INVOKER_SERVICE_ACCOUNT_EMAIL": "tasks-invoker@example.iam.gserviceaccount.com",
            "TASKS_EXPECTED_AUDIENCE": "https://example.run.app/api/tasks/send-email",
        }
    )

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def create_user(app):
    def _create_user(email: str, employee_approved: bool, role: Role = Role.EMPLOYEE) -> int:
        user = User(email=email, role=role, employee_approved=employee_approved)
        db.session.add(user)
        db.session.commit()
        return user.id

    return _create_user
