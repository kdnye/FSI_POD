import os

import pytest

from app import create_app, db
from models import Role, User

os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("PUBLIC_SERVICE_URL", "https://example.run.app")
os.environ.setdefault("TASK_SERVICE_ACCOUNT_EMAIL", "tasks-invoker@example.iam.gserviceaccount.com")


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "GCP_PROJECT_ID": "test-project",
            "PUBLIC_SERVICE_URL": "https://example.run.app",
            "TASK_SERVICE_ACCOUNT_EMAIL": "tasks-invoker@example.iam.gserviceaccount.com",
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
