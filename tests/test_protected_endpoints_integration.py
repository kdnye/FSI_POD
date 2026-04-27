from models import Role


def test_protected_routes_require_authentication(client):
    dashboard_response = client.get("/auth/internal/dashboard")
    gate_response = client.get("/auth/gate/internal_dashboard/view")

    assert dashboard_response.status_code == 401
    assert gate_response.status_code == 401


def test_unapproved_user_sees_mixed_protected_outcomes(client, create_user):
    user_id = create_user("not-approved@example.com", employee_approved=False, role=Role.ADMIN)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    dashboard_response = client.get("/auth/internal/dashboard", follow_redirects=False)
    gate_response = client.get("/auth/gate/internal_dashboard/view")

    assert dashboard_response.status_code == 302
    assert dashboard_response.headers["Location"].endswith("/auth/pending-approval")

    assert gate_response.status_code == 403
    assert gate_response.get_json()["error"] == "Employee approval is required."
    assert "approve your employee account" in gate_response.get_json()["remediation"]


def test_approved_admin_receives_expected_statuses_by_policy(client, create_user):
    user_id = create_user("approved-admin@example.com", employee_approved=True, role=Role.ADMIN)

    with client.session_transaction() as sess:
        sess["current_user_id"] = user_id

    dashboard_response = client.get("/auth/internal/dashboard")
    allowed_gate = client.get("/auth/gate/admin_panel/manage")
    denied_gate = client.get("/auth/gate/admin_panel/delete")

    assert dashboard_response.status_code == 200
    assert allowed_gate.status_code == 200

    assert denied_gate.status_code == 403
    assert denied_gate.get_json()["error"] == "Access denied."
    assert "ACCESS_DENIED action_undefined" in denied_gate.get_json()["detail"]
