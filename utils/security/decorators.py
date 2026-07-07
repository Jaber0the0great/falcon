"""Decorator-based security guards for Flask route handlers.

Each decorator wraps a view function and returns a standard Flask response
when the guard condition is not met, without executing the view.
"""

import functools
from typing import Any, Callable

from flask import jsonify, make_response, session as flask_session

from utils.security.constants import ERR_ADMIN_REQUIRED, ERR_AUTH_REQUIRED, ERR_INVALID_JSON
from utils.security.exceptions import AuthenticationError, AuthorizationError, ValidationError


def login_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that ensures the user is authenticated.

    Returns a 401 JSON response if ``user_id`` is not present in the session.

    Usage::

        @app.route('/protected')
        @login_required
        def protected_route():
            return jsonify({"success": True})
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not flask_session.get("user_id"):
            return make_response(jsonify({"success": False, "error": ERR_AUTH_REQUIRED}), 401)
        return f(*args, **kwargs)

    return wrapper


def admin_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that ensures the user is an administrator.

    Returns a 401 JSON response if the user is not authenticated or not an admin.

    Usage::

        @app.route('/admin/panel')
        @admin_required
        def admin_panel():
            return jsonify({"success": True})
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not flask_session.get("user_id"):
            return make_response(jsonify({"success": False, "error": ERR_AUTH_REQUIRED}), 401)
        if not flask_session.get("admin_logged_in"):
            return make_response(jsonify({"success": False, "error": ERR_ADMIN_REQUIRED}), 401)
        return f(*args, **kwargs)

    return wrapper


def json_required(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that ensures the request has a valid JSON body.

    Returns a 400 JSON response if the Content-Type is not JSON or the body
    cannot be parsed.

    Usage::

        @app.route('/submit', methods=['POST'])
        @json_required
        def submit():
            data = flask.request.get_json()
            ...
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from flask import request

        data = request.get_json(silent=True)
        if data is None:
            return make_response(jsonify({"success": False, "error": ERR_INVALID_JSON}), 400)
        return f(*args, **kwargs)

    return wrapper
