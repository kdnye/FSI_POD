from __future__ import annotations

from dataclasses import dataclass

from models import Role


ROLE_HIERARCHY: dict[Role, int] = {
    Role.EMPLOYEE: 1,
    Role.SUPERVISOR: 2,
    Role.FINANCE: 3,
    Role.ADMIN: 4,
    Role.ADMINISTRATOR: 4,
}

# resource -> action -> minimum role required
PERMISSION_POLICY: dict[str, dict[str, Role]] = {
    "internal_dashboard": {
        "view": Role.EMPLOYEE,
    },
    "team_approvals": {
        "approve": Role.SUPERVISOR,
    },
    "finance_ledger": {
        "view": Role.FINANCE,
        "approve": Role.FINANCE,
    },
    "admin_panel": {
        "manage": Role.ADMIN,
    },
}


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    message: str


def evaluate_access(*, user_role: Role | str, resource: str, action: str) -> AccessDecision:
    try:
        normalized_role = Role.from_value(user_role)
    except ValueError:
        return AccessDecision(
            allowed=False,
            message=(
                f"ACCESS_DENIED invalid_role resource={resource.strip().lower()} "
                f"action={action.strip().lower()} role={str(user_role).strip()}"
            ),
        )

    normalized_resource = resource.strip().lower()
    normalized_action = action.strip().lower()

    actions = PERMISSION_POLICY.get(normalized_resource)
    if actions is None:
        return AccessDecision(
            allowed=False,
            message=(
                f"ACCESS_DENIED policy_missing resource={normalized_resource} "
                f"action={normalized_action} role={normalized_role.value}"
            ),
        )

    minimum_role = actions.get(normalized_action)
    if minimum_role is None:
        return AccessDecision(
            allowed=False,
            message=(
                f"ACCESS_DENIED action_undefined resource={normalized_resource} "
                f"action={normalized_action} role={normalized_role.value}"
            ),
        )

    if ROLE_HIERARCHY[normalized_role] < ROLE_HIERARCHY[minimum_role]:
        return AccessDecision(
            allowed=False,
            message=(
                f"ACCESS_DENIED insufficient_role resource={normalized_resource} "
                f"action={normalized_action} role={normalized_role.value} "
                f"required={minimum_role.value}"
            ),
        )

    return AccessDecision(
        allowed=True,
        message=(
            f"ACCESS_GRANTED resource={normalized_resource} action={normalized_action} "
            f"role={normalized_role.value}"
        ),
    )
