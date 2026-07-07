"""Permission and authorization helpers.

These functions encapsulate the most common access-control checks used
throughout the application.  Every ``require_*`` function raises a typed
exception on failure; ``is_*`` functions return a boolean for callers
that need conditional logic.
"""

from typing import Any, Dict, Optional

from sqlalchemy.orm import scoped_session

from utils.security.constants import (
    ERR_ADMIN_REQUIRED,
    ERR_AUTH_REQUIRED,
    ERR_NOT_AUTHORIZED,
    ERR_NOT_GROUP_OWNER,
    ERR_USER_BANNED,
)
from utils.security.exceptions import AuthenticationError, AuthorizationError


def require_authenticated(session: Dict[str, Any]) -> int:
    """Require a valid authenticated session.

    Args:
        session: The Flask ``session`` proxy dictionary.

    Returns:
        The authenticated user's ID.

    Raises:
        AuthenticationError: If ``user_id`` is not present in the session.
    """
    user_id = session.get("user_id")
    if not user_id:
        raise AuthenticationError(ERR_AUTH_REQUIRED)
    return user_id


def require_admin(session: Dict[str, Any]) -> None:
    """Require that the current session belongs to an administrator.

    Args:
        session: The Flask ``session`` proxy dictionary.

    Raises:
        AuthenticationError: If the user is not authenticated.
        AuthorizationError: If the user is not an administrator.
    """
    require_authenticated(session)
    if not session.get("admin_logged_in"):
        raise AuthorizationError(ERR_ADMIN_REQUIRED, status_code=401)


def get_current_username(session: Dict[str, Any]) -> str:
    """Return the username stored in the session.

    Args:
        session: The Flask ``session`` proxy dictionary.

    Returns:
        The current user's username.

    Raises:
        AuthenticationError: If the user is not authenticated or the
            username is not set.
    """
    require_authenticated(session)
    username = session.get("username")
    if not username:
        raise AuthenticationError(ERR_AUTH_REQUIRED)
    return username


def is_owner(current_user: str, resource_owner: str) -> bool:
    """Check whether *current_user* owns a resource.

    Args:
        current_user: The authenticated user's identifier.
        resource_owner: The owner of the resource being accessed.

    Returns:
        ``True`` if the users match, ``False`` otherwise.
    """
    return current_user == resource_owner


def require_owner(current_user: str, resource_owner: str) -> None:
    """Require that *current_user* owns the resource.

    Args:
        current_user: The authenticated user's identifier.
        resource_owner: The owner of the resource being accessed.

    Raises:
        AuthorizationError: If the users do not match.
    """
    if not is_owner(current_user, resource_owner):
        raise AuthorizationError(ERR_NOT_AUTHORIZED)


def is_group_owner(current_user: str, group: Any) -> bool:
    """Check whether *current_user* is the owner of a group.

    Args:
        current_user: The authenticated user's username.
        group: A ``Group`` model instance (must have an ``owner_username`` attribute).

    Returns:
        ``True`` if the user is the group owner, ``False`` otherwise.
    """
    return is_owner(current_user, getattr(group, "owner_username", None))


def require_group_owner(current_user: str, group: Any) -> None:
    """Require that *current_user* is the owner of *group*.

    Args:
        current_user: The authenticated user's username.
        group: A ``Group`` model instance.

    Raises:
        AuthorizationError: If the user is not the group owner.
    """
    if not is_group_owner(current_user, group):
        raise AuthorizationError(ERR_NOT_GROUP_OWNER)


def is_group_member(
    current_user: str,
    group_name: str,
    db_session: scoped_session,
) -> bool:
    """Check whether *current_user* is a member of a group.

    Args:
        current_user: The authenticated user's username.
        group_name: The name of the group to check.
        db_session: A SQLAlchemy database session.

    Returns:
        ``True`` if the user is a member, ``False`` otherwise.
    """
    from models.models import GroupMember

    member = GroupMember.query.filter_by(
        group_name=group_name, username=current_user
    ).first()
    return member is not None


def require_group_member(
    current_user: str,
    group_name: str,
    db_session: scoped_session,
) -> None:
    """Require that *current_user* is a member of *group_name*.

    Args:
        current_user: The authenticated user's username.
        group_name: The name of the group.
        db_session: A SQLAlchemy database session.

    Raises:
        AuthorizationError: If the user is not a member of the group.
    """
    if not is_group_member(current_user, group_name, db_session):
        raise AuthorizationError(ERR_NOT_AUTHORIZED, status_code=403)
