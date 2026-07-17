"""Active-role context for accounts that hold more than one role (today:
an Admin who also has a linked Teacher profile — see User.is_teacher_linked
in models.py). A single logged-in session can only act as one role at a
time; this module is the one place that default/lookup logic lives, so
blueprints/auth.py (login) and the two blueprints' gatekeeping decorators
(blueprints/admin/__init__.py, blueprints/teacher.py) can't drift apart."""
from flask import session


def default_active_role(user):
    """The role a session should start in for this user: 'admin' for a
    dual-role account (admin + linked teacher profile), otherwise just
    their single real role."""
    if user.role == 'admin' and user.is_teacher_linked:
        return 'admin'
    return user.role


def get_active_role(user):
    """session['active_role'], lazily initialized with default_active_role()
    if missing. Login sets this explicitly, but Flask-Login's "remember me"
    cookie can silently re-authenticate a returning user without ever
    running the login() view — this fallback keeps that path from locking
    a legitimately logged-in dual-role user out with a false 403."""
    if 'active_role' not in session:
        session['active_role'] = default_active_role(user)
    return session['active_role']
