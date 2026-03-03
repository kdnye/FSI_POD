from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app import db
from app.blueprints.account.forms import ProfileForm, SettingsForm
from app.blueprints.auth.guards import require_authenticated
from models import Role, User


account_bp = Blueprint("account", __name__, url_prefix="/account")


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

        if user.id == g.current_user.id and (updated_role != current_role or not is_active or not employee_approved):
            flash("You cannot remove your own administrative access.", "error")
            return redirect(url_for("account.admin_users"))

        user.role = updated_role.value
        user.employee_approved = employee_approved
        user.is_active = is_active
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
