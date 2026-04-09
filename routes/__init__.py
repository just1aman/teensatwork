from functools import wraps
from flask import abort, redirect, url_for
from flask_login import current_user


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                abort(403)
            if not current_user.is_approved and current_user.role != 'admin':
                return redirect(url_for('auth.pending'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
