from app import db
from models import Role, User


def _create_session_user(client, email="account@example.com"):
    user = User(
        email=email,
        password_hash="pbkdf2:sha256:1$dummy$dummy",
        employee_approved=True,
        name="Account User",
    )
    db.session.add(user)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["current_user_id"] = user.id

    return user


def test_account_pages_require_login(client):
    assert client.get("/account/profile").status_code == 302
    assert client.get("/account/settings").status_code == 302


def test_profile_page_renders_for_authenticated_user(client):
    _create_session_user(client)

    response = client.get("/account/profile")

    assert response.status_code == 200
    assert b"Profile" in response.data
    assert b"Save profile" in response.data


def test_settings_page_renders_for_authenticated_user(client):
    _create_session_user(client, email="settings@example.com")

    response = client.get("/account/settings")

    assert response.status_code == 200
    assert b"Settings" in response.data
    assert b"Email notifications" in response.data


def test_admin_users_page_requires_admin_role(client):
    _create_session_user(client, email="employee@example.com")

    response = client.get("/account/admin/users", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/pod/event")


def test_admin_users_page_renders_for_admin(client):
    admin = _create_session_user(client, email="admin@example.com")
    admin.role = Role.ADMIN.value
    db.session.commit()

    response = client.get("/account/admin/users")

    assert response.status_code == 200
    assert b"Admin Dashboard" in response.data
    assert b"Manage user access" in response.data


def test_admin_can_update_user_permissions(client):
    admin = _create_session_user(client, email="admin-update@example.com")
    admin.role = Role.ADMIN.value

    target_user = User(
        email="driver@example.com",
        password_hash="pbkdf2:sha256:1$dummy$dummy",
        role=Role.EMPLOYEE.value,
        employee_approved=False,
        is_active=True,
    )
    db.session.add(target_user)
    db.session.commit()

    response = client.post(
        "/account/admin/users",
        data={
            "user_id": str(target_user.id),
            "role": Role.SUPERVISOR.value,
            "employee_approved": "on",
            "is_active": "on",
        },
        follow_redirects=False,
    )

    db.session.refresh(target_user)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/admin/users")
    assert target_user.role == Role.SUPERVISOR.value
    assert target_user.employee_approved is True
    assert target_user.is_active is True
