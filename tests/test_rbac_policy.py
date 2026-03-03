import pytest

from app.services.rbac import PERMISSION_POLICY, ROLE_HIERARCHY, evaluate_access
from models import Role


@pytest.mark.parametrize(
    "resource,action,min_role",
    [
        (resource, action, min_role)
        for resource, actions in PERMISSION_POLICY.items()
        for action, min_role in actions.items()
    ],
)
def test_role_resource_authorization_matrix(resource, action, min_role):
    for role in ROLE_HIERARCHY:
        decision = evaluate_access(user_role=role, resource=resource, action=action)
        expected_allowed = ROLE_HIERARCHY[role] >= ROLE_HIERARCHY[min_role]

        assert decision.allowed is expected_allowed
        if expected_allowed:
            assert "ACCESS_GRANTED" in decision.message
        else:
            assert "ACCESS_DENIED insufficient_role" in decision.message


def test_policy_lookup_is_case_and_whitespace_insensitive():
    decision = evaluate_access(user_role=Role.ADMIN, resource="  ADMIN_PANEL ", action=" MANAGE  ")

    assert decision.allowed is True
    assert "resource=admin_panel" in decision.message
    assert "action=manage" in decision.message


def test_unknown_resource_and_action_are_denied_with_audit_messages():
    missing_policy = evaluate_access(user_role=Role.ADMIN, resource="missing", action="view")
    missing_action = evaluate_access(user_role=Role.ADMIN, resource="admin_panel", action="delete")

    assert missing_policy.allowed is False
    assert "ACCESS_DENIED policy_missing" in missing_policy.message

    assert missing_action.allowed is False
    assert "ACCESS_DENIED action_undefined" in missing_action.message


def test_administrator_alias_is_treated_as_admin():
    decision = evaluate_access(user_role="administrator", resource="admin_panel", action="manage")

    assert decision.allowed is True
    assert "role=ADMINISTRATOR" in decision.message


def test_ops_override_allows_load_board_and_pod_history_without_admin_role():
    load_board_decision = evaluate_access(
        user_role=Role.EMPLOYEE,
        resource="load_board",
        action="manage",
        is_ops=True,
    )
    pod_history_decision = evaluate_access(
        user_role=Role.SUPERVISOR,
        resource="pod_history",
        action="export",
        is_ops=True,
    )

    assert load_board_decision.allowed is True
    assert "ACCESS_GRANTED ops_override" in load_board_decision.message
    assert pod_history_decision.allowed is True
    assert "ACCESS_GRANTED ops_override" in pod_history_decision.message


def test_non_ops_users_still_need_admin_for_ops_resources():
    decision = evaluate_access(user_role=Role.SUPERVISOR, resource="load_board", action="manage")

    assert decision.allowed is False
    assert "ACCESS_DENIED insufficient_role" in decision.message
