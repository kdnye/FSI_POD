from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import abort, g, jsonify, redirect, session, url_for

from app import db
from models import User


def _load_current_user() -> User | None:
    """Resolve the current user from session state."""
    user_id = session.get("current_user_id")
    if user_id is None:
        return None
    return db.session.get(User, user_id)


def require_employee_approval(
    redirect_endpoint: str | None = None,
    unauthenticated_redirect_endpoint: str | None = "auth.login_page",
) -> Callable:
    """Block access when the current user is not approved."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is None:
                if unauthenticated_redirect_endpoint:
                    return redirect(url_for(unauthenticated_redirect_endpoint))
                abort(401)

            if user.employee_approved:
                return view(*args, **kwargs)

            if redirect_endpoint:
                return redirect(url_for(redirect_endpoint))

            return jsonify({"error": "Employee approval is required."}), 403

        return wrapped

    return decorator


def require_authenticated(redirect_endpoint: str = "auth.login_page") -> Callable:
    """Require a signed-in user session before allowing access."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if user is not None:
                return view(*args, **kwargs)

            if redirect_endpoint:
                return redirect(url_for(redirect_endpoint))

            abort(401)

        return wrapped

    return decorator
