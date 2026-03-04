from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app import db
from app.blueprints.account.forms import ProfileForm, SettingsForm
from app.blueprints.auth.guards import require_authenticated
from models import NotificationSettings, Role, User


account_bp = Blueprint("account", __name__, url_prefix="/account")


def _has_privileged_access(*, role: Role, employee_approved: bool, is_active: bool, is_ops: bool) -> bool:
    if not employee_approved or not is_active:
        return False
    return role.is_admin or is_ops


@account_bp.route("/profile", methods=["GET", "POST"])
@require_authenticated()
def profile():
    user = g.current_user
    form = ProfileForm(obj=user)

    if form.validate_on_submit():
        user.full_name = form.full_name.data.strip() if form.full_name.data else None
        user.avatar_url = form.avatar_url.data.strip() if form.avatar_url.data else None
        user.phone = form.phone.data.strip() if form.phone.data else None
        user.bio = form.bio.data.strip() if form.bio.data else None
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("account.profile"))

    return render_template("account/profile.html", title="Profile", form=form)


@account_bp.route("/settings", methods=["GET", "POST"])
@require_authenticated()
def settings():
    user = g.current_user
    form = SettingsForm(obj=user)

    if form.validate_on_submit():
        user.theme = form.theme.data
        user.email_notifications = form.email_notifications.data
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("account.settings"))

    return render_template("account/settings.html", title="Settings", form=form)


@account_bp.route("/admin/users", methods=["GET", "POST"])
@require_authenticated()
def admin_users():
    current_role = Role.from_value(getattr(g.current_user, "role", ""))
    if not current_role.is_admin:
        flash("Administrator access is required.", "error")
        return redirect(url_for("paperwork.log_pod_event"))

    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        role_value = request.form.get("role", "").strip().upper()
        employee_approved = request.form.get("employee_approved") == "on"
        is_active = request.form.get("is_active") == "on"
        is_ops = request.form.get("is_ops") == "on"

        if not user_id.isdigit():
            flash("Invalid user selection.", "error")
            return redirect(url_for("account.admin_users"))

        try:
            updated_role = Role.from_value(role_value)
        except ValueError:
            flash("Invalid role selection.", "error")
            return redirect(url_for("account.admin_users"))

        user = db.session.get(User, int(user_id))
        if user is None:
            flash("User not found.", "error")
            return redirect(url_for("account.admin_users"))

        if user.id == g.current_user.id:
            will_keep_privileged_access = _has_privileged_access(
                role=updated_role,
                employee_approved=employee_approved,
                is_active=is_active,
                is_ops=is_ops,
            )
            if not will_keep_privileged_access:
                flash("You cannot remove your own privileged access.", "error")
                return redirect(url_for("account.admin_users"))

        user.role = updated_role.value
        user.employee_approved = employee_approved
        user.is_active = is_active
        user.is_ops = is_ops
        db.session.commit()
        flash(f"Updated access for {user.email}.", "success")
        return redirect(url_for("account.admin_users"))

    users = User.query.order_by(User.email.asc()).all()
    return render_template(
        "account/admin_users.html",
        title="Admin Dashboard",
        users=users,
        role_choices=[role.value for role in Role],
    )


@account_bp.route("/admin/notifications", methods=["GET", "POST"])
@require_authenticated()
def admin_notifications():
    current_role = Role.from_value(getattr(g.current_user, "role", ""))
    if not current_role.is_admin:
        flash("Administrator access is required.", "error")
        return redirect(url_for("paperwork.log_pod_event"))

    settings = NotificationSettings.query.order_by(NotificationSettings.id.asc()).first()
    if settings is None:
        settings = NotificationSettings()
        db.session.add(settings)
        db.session.flush()

    if request.method == "POST":
        settings.notify_shipper_pickup = request.form.get("notify_shipper_pickup") == "on"
        settings.notify_origin_drop = request.form.get("notify_origin_drop") == "on"
        settings.notify_dest_pickup = request.form.get("notify_dest_pickup") == "on"
        settings.notify_consignee_drop = request.form.get("notify_consignee_drop") == "on"
        settings.custom_cc_emails = (request.form.get("custom_cc_emails") or "").strip() or None
        db.session.commit()
        flash("Notification settings saved.", "success")
        return redirect(url_for("account.admin_notifications"))

    return render_template(
        "account/admin_notifications.html",
        title="Admin Notifications",
        settings=settings,
    )
