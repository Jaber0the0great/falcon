"""Input validation functions.

Every public function validates a specific kind of user input and either returns
the validated (and possibly normalized) value or raises a ValidationError with
a descriptive message.
"""

from typing import Any, Dict, List, Tuple

from flask import Request

from utils.security.constants import (
    ERR_GROUP_NAME_REQUIRED,
    ERR_GROUP_NAME_TAKEN,
    ERR_INVALID_GROUP_NAME,
    ERR_INVALID_PASSWORD,
    ERR_INVALID_USERNAME,
    ERR_MEMBERS_MUST_BE_LIST,
    ERR_MESSAGE_TOO_LONG,
    ERR_MISSING_PARAMETERS,
    ERR_PASSWORD_REQUIRED,
    ERR_SAME_USERNAME,
    ERR_TOO_MANY_MEMBERS,
    ERR_USERNAME_AND_PASSWORD_REQUIRED,
    ERR_USERNAME_REQUIRED,
    GROUP_NAME_PATTERN,
    MAX_GROUP_MEMBERS_PER_REQUEST,
    MAX_GROUP_NAME_LENGTH,
    MAX_MESSAGE_CONTENT_LENGTH,
    MAX_PASSWORD_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_GROUP_NAME_LENGTH,
    MIN_PASSWORD_LENGTH,
    MIN_USERNAME_LENGTH,
    USERNAME_PATTERN,
)
from utils.security.exceptions import ValidationError


def validate_username(username: Any) -> str:
    """Validate and normalize a username.

    Args:
        username: The raw username value (may be None or any type).

    Returns:
        The trimmed, validated username string.

    Raises:
        ValidationError: If the username is missing, too short, too long,
            or contains disallowed characters.
    """
    if not username or not isinstance(username, str) or not username.strip():
        raise ValidationError(ERR_USERNAME_REQUIRED)
    username = username.strip()
    if len(username) < MIN_USERNAME_LENGTH or len(username) > MAX_USERNAME_LENGTH:
        raise ValidationError(ERR_INVALID_USERNAME)
    if not USERNAME_PATTERN.match(username):
        raise ValidationError(ERR_INVALID_USERNAME)
    return username


def validate_password(password: Any) -> str:
    """Validate a password.

    Args:
        password: The raw password value (may be None or any type).

    Returns:
        The password string (unchanged).

    Raises:
        ValidationError: If the password is missing, too short, or too long.
    """
    if not password or not isinstance(password, str) or not password:
        raise ValidationError(ERR_PASSWORD_REQUIRED)
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationError(ERR_INVALID_PASSWORD)
    return password


def validate_group_name(name: Any) -> str:
    """Validate a group name.

    Args:
        name: The raw group name value.

    Returns:
        The trimmed, validated group name.

    Raises:
        ValidationError: If the name is missing, too short, too long, contains
            disallowed characters, or is the reserved name "All".
    """
    if not name or not isinstance(name, str) or not name.strip():
        raise ValidationError(ERR_GROUP_NAME_REQUIRED)
    name = name.strip()
    if name.lower() == "all":
        raise ValidationError(ERR_SAME_USERNAME)
    if not GROUP_NAME_PATTERN.match(name):
        raise ValidationError(ERR_INVALID_GROUP_NAME)
    if len(name) < MIN_GROUP_NAME_LENGTH or len(name) > MAX_GROUP_NAME_LENGTH:
        raise ValidationError(ERR_INVALID_GROUP_NAME)
    return name


def validate_required_fields(data: Dict[str, Any], *fields: str) -> Dict[str, Any]:
    """Ensure that all specified fields exist and are non-empty in *data*.

    Args:
        data: The dictionary to check (typically ``request.json`` or ``request.form``).
        *fields: One or more field names that must be present.

    Returns:
        The *data* dict unchanged.

    Raises:
        ValidationError: If any field is missing, None, or an empty string.
    """
    missing = [f for f in fields if not data or not data.get(f)]
    if missing:
        raise ValidationError(ERR_MISSING_PARAMETERS)
    return data


def validate_string_length(
    value: str,
    min_len: int,
    max_len: int,
    name: str = "Value",
) -> str:
    """Validate that a string falls within a length range.

    Args:
        value: The string to check.
        min_len: Minimum allowed length (inclusive).
        max_len: Maximum allowed length (inclusive).
        name: Human-readable name for the field (used in the error message).

    Returns:
        The original string unchanged.

    Raises:
        ValidationError: If the string is too short or too long.
    """
    if len(value) < min_len:
        raise ValidationError(f"{name} must be at least {min_len} characters.")
    if len(value) > max_len:
        raise ValidationError(f"{name} must be at most {max_len} characters.")
    return value


def validate_json_request(request: Request) -> Dict[str, Any]:
    """Extract and validate a JSON body from a Flask request.

    Args:
        request: The incoming Flask request object.

    Returns:
        The parsed JSON dictionary.

    Raises:
        ValidationError: If the Content-Type is not JSON or the body is
            not valid JSON.
    """
    data = request.get_json(silent=True)
    if data is None:
        raise ValidationError(ERR_INVALID_JSON)
    return data


def validate_message_content(content: Any) -> str:
    """Validate message content length.

    Args:
        content: The raw message content.

    Returns:
        The content string unchanged.

    Raises:
        ValidationError: If content exceeds the maximum allowed length.
    """
    if content and isinstance(content, str) and len(content) > MAX_MESSAGE_CONTENT_LENGTH:
        raise ValidationError(ERR_MESSAGE_TOO_LONG)
    return content or ""


def validate_username_list(
    usernames: Any,
    max_count: int = MAX_GROUP_MEMBERS_PER_REQUEST,
) -> List[str]:
    """Validate a list of usernames.

    Rules:
    - ``None`` is treated as an empty list.
    - Must be a ``list`` (type check).
    - Must not exceed *max_count* items.
    - Each item must be a non-empty string.
    - Each item is validated via :func:`validate_username`.
    - Case-insensitive deduplication (first occurrence wins).

    Args:
        usernames: The raw value from the request body.
        max_count: Maximum number of allowed usernames.

    Returns:
        A deduplicated list of validated, stripped username strings.

    Raises:
        ValidationError: If the value is not a list, exceeds the count
            limit, or any element is not a valid username.
    """
    if usernames is None:
        return []
    if not isinstance(usernames, list):
        raise ValidationError(ERR_MEMBERS_MUST_BE_LIST)
    if len(usernames) > max_count:
        raise ValidationError(ERR_TOO_MANY_MEMBERS)

    validated: List[str] = []
    seen: set = set()

    for item in usernames:
        if not isinstance(item, str):
            raise ValidationError("Each member must be a string.")
        item = item.strip()
        if not item:
            # Silently skip empty/whitespace entries to preserve pre-existing
            # behavior: the original code allowed empty-string members in the
            # request body — they simply failed to match any User in the DB
            # and were ignored.  Changing this to an error would break clients
            # that include trailing or empty entries in the members list.
            continue
        username = validate_username(item)
        key = username.lower()
        if key not in seen:
            seen.add(key)
            validated.append(username)

    return validated
