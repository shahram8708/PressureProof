from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user


def login_required(view_function):
    @wraps(view_function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login_get", next=next_url))
        return view_function(*args, **kwargs)

    return wrapped


def email_verified_required(view_function):
    @wraps(view_function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login_get"))

        if not current_user.email_verified:
            flash("Please verify your email address to continue.", "warning")
            return redirect(url_for("auth.login_get"))

        return view_function(*args, **kwargs)

    return wrapped
