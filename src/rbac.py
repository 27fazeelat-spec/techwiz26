"""Role-based access control (SRS FR ii). Permissions come from config/permissions.yaml."""
from fnmatch import fnmatch
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from config.loader import load_config


def permissions_for(app_role):
    return load_config("permissions")["roles"].get(app_role, {}).get("permissions", [])


def role_has_permission(app_role, permission):
    return any(fnmatch(permission, granted) for granted in permissions_for(app_role))


def has_permission(user, permission):
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return any(fnmatch(permission, granted) for granted in permissions_for(user.app_role))


def require_permission(permission):
    """Route decorator: signed-in users without the permission get 403, never a silent redirect."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_permission(current_user, permission):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
