from models import Role


def test_approved_user_can_access_protected_routes(client, create_user):
    user_id = create_user("approved@example.com", employee_approved=True)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/internal/dashboard")

    assert response.status_code == 200
    assert response.get_json() == {"dashboard": "internal-tools"}


def test_unapproved_user_is_redirected_to_pending_page(client, create_user):
    user_id = create_user("pending@example.com", employee_approved=False)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/internal/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/pending-approval")

    pending_page = client.get(response.headers["Location"])
    assert pending_page.status_code == 403
    assert b"Approval Pending" in pending_page.data


def test_unapproved_user_gets_403_on_api_guard(client, create_user):
    user_id = create_user("api-pending@example.com", employee_approved=False)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/gate/internal_dashboard/view")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Employee approval is required."
    assert "approve your employee account" in response.get_json()["remediation"]


def test_employee_denied_finance_action(client, create_user):
    user_id = create_user("employee@example.com", employee_approved=True, role=Role.EMPLOYEE)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/gate/finance_ledger/approve")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Access denied."
    assert "ACCESS_DENIED insufficient_role" in response.get_json()["detail"]
    assert "required=FINANCE" in response.get_json()["detail"]
    assert "Request a role" in response.get_json()["remediation"]


def test_finance_can_approve_finance_action(client, create_user):
    user_id = create_user("finance@example.com", employee_approved=True, role=Role.FINANCE)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/gate/finance_ledger/approve")

    assert response.status_code == 200
    assert response.get_json() == {
        "resource": "finance_ledger",
        "action": "approve",
        "allowed": True,
    }


def test_supervisor_can_approve_team_action(client, create_user):
    user_id = create_user("supervisor@example.com", employee_approved=True, role=Role.SUPERVISOR)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/gate/team_approvals/approve")

    assert response.status_code == 200
    assert response.get_json()["allowed"] is True


def test_unknown_policy_target_returns_403_with_audit_message(client, create_user):
    user_id = create_user("admin@example.com", employee_approved=True, role=Role.ADMIN)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    response = client.get("/auth/gate/unknown_resource/delete")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Access denied."
    assert "ACCESS_DENIED policy_missing" in response.get_json()["detail"]
