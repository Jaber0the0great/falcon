from flask import jsonify


def success_response(data=None, message=None, status_code=200):
    """Return a standard success response.

    {
        "success": true,
        "data": <data>,
        "message": <message>   # optional
    }
    """
    body = {"success": True}
    if data is not None:
        body["data"] = data
    if message is not None:
        body["message"] = message
    return jsonify(body), status_code


def error_response(code, message, details=None, status_code=None):
    """Return a standard error response.

    {
        "success": false,
        "error": {
            "code": <code>,
            "message": <message>,
            "details": <details>   # optional
        }
    }

    *code* is a string like ``"AUTH_INVALID_CREDENTIALS"``.
    If *status_code* is omitted, it defaults to 400.
    """
    if status_code is None:
        status_code = 400
    body = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status_code


def paginated_response(items, total, offset, limit, message=None):
    """Return a standard paginated response.

    {
        "success": true,
        "data": [<items>],
        "meta": {
            "total": <total>,
            "offset": <offset>,
            "limit": <limit>
        },
        "message": <message>   # optional
    }
    """
    body = {
        "success": True,
        "data": items,
        "meta": {
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    }
    if message is not None:
        body["message"] = message
    return jsonify(body), 200
