import logging
from datetime import datetime
from flask import Blueprint, request, session
from models.models import User, Message, Group, GroupMember, GroupInvite, GroupJoinRequest, UsernameHistory
from database.database import db

from sqlalchemy import func, text
from utils.security import (
    validate_username,
    validate_password,
    ValidationError,
    rate_limit,
    user_key,
)
from utils.api import success_response, error_response, ErrorCode
from utils.security.constants import RESERVED_USERNAMES, USERNAME_CHANGE_COOLDOWN_DAYS
from utils.presence import registry as presence_registry

logger = logging.getLogger(__name__)
settings_bp = Blueprint('settings', __name__, url_prefix='/api/settings')


@settings_bp.route('', methods=['GET'])
@rate_limit(30, key_func=user_key)
def get_settings():
    user = User.query.get(session.get('user_id'))
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)
    return success_response({
        "username": user.username,
        "theme": user.theme or 'system',
        "default_status": user.default_status or 'Available',
    })


@settings_bp.route('/theme', methods=['POST'])
@rate_limit(10, key_func=user_key)
def update_theme():
    user = User.query.get(session.get('user_id'))
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)

    data = request.get_json(silent=True)
    if not data or 'theme' not in data:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Theme is required", status_code=400)

    theme = data['theme']
    if theme not in ('light', 'dark', 'system'):
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Theme must be 'light', 'dark', or 'system'", status_code=400)

    user.theme = theme
    db.session.commit()
    logger.info("User '%s' changed theme to '%s'", user.username, theme)
    return success_response({"theme": theme})


@settings_bp.route('/default-status', methods=['POST'])
@rate_limit(10, key_func=user_key)
def update_default_status():
    user = User.query.get(session.get('user_id'))
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)

    data = request.get_json(silent=True)
    if not data or 'default_status' not in data:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Default status is required", status_code=400)

    default_status = data['default_status']
    if default_status not in ('Available', 'Busy', 'Away'):
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Default status must be 'Available', 'Busy', or 'Away'", status_code=400)

    user.default_status = default_status
    db.session.commit()
    logger.info("User '%s' changed default_status to '%s'", user.username, default_status)
    return success_response({"default_status": default_status})


@settings_bp.route('/check-username', methods=['GET'])
@rate_limit(30, key_func=user_key)
def check_username():
    new_username = request.args.get('username', '').strip()
    if not new_username:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Username parameter required", status_code=400)

    try:
        validate_username(new_username)
    except ValidationError as e:
        return success_response({"available": False, "reason": e.message})

    if new_username.lower() in RESERVED_USERNAMES:
        return success_response({"available": False, "reason": "This username is reserved"})

    existing = User.query.filter(func.lower(User.username) == func.lower(new_username)).first()
    if existing:
        return success_response({"available": False, "reason": "Username already taken"})

    return success_response({"available": True})


def _validate_rename(user, new_username):
    """Validate all pre-rename checks. Raises ValueError on failure."""
    if new_username == user.username:
        raise ValueError("New username must be different")

    validate_username(new_username)

    if new_username.lower() in RESERVED_USERNAMES:
        raise ValueError("This username is reserved")

    existing = User.query.filter(func.lower(User.username) == func.lower(new_username)).first()
    if existing:
        raise ValueError("Username already taken")

    existing_group = Group.query.filter(func.lower(Group.name) == func.lower(new_username)).first()
    if existing_group:
        raise ValueError("Username conflicts with group name")

    last_change = UsernameHistory.query.filter_by(user_id=user.id).order_by(
        UsernameHistory.changed_at.desc()
    ).first()
    if last_change:
        days_since = (datetime.utcnow() - last_change.changed_at).days
        if days_since < USERNAME_CHANGE_COOLDOWN_DAYS:
            remaining = USERNAME_CHANGE_COOLDOWN_DAYS - days_since
            raise ValueError(f"Must wait {remaining} more day(s)")


def _rename_user(user_id, old_username, new_username):
    """Execute atomic rename using BEGIN IMMEDIATE. Returns no value on success."""
    user = User.query.get(user_id)
    if not user:
        raise ValueError("User not found")

    _validate_rename(user, new_username)

    db.session.execute(text("BEGIN IMMEDIATE"))
    try:
        user.username = new_username

        from sqlalchemy import update as sa_update

        db.session.execute(
            sa_update(Message).where(Message.sender == old_username)
            .values(sender=new_username)
        )
        db.session.execute(
            sa_update(Message).where(Message.recipient == old_username)
            .values(recipient=new_username)
        )
        db.session.execute(
            sa_update(Message).where(Message.reply_to == old_username)
            .values(reply_to=new_username)
        )
        db.session.execute(
            sa_update(Group).where(Group.owner_username == old_username)
            .values(owner_username=new_username)
        )
        db.session.execute(
            sa_update(GroupMember).where(GroupMember.username == old_username)
            .values(username=new_username)
        )
        db.session.execute(
            sa_update(GroupInvite).where(GroupInvite.username == old_username)
            .values(username=new_username)
        )
        db.session.execute(
            sa_update(GroupInvite).where(GroupInvite.invited_by == old_username)
            .values(invited_by=new_username)
        )
        db.session.execute(
            sa_update(GroupJoinRequest).where(GroupJoinRequest.username == old_username)
            .values(username=new_username)
        )

        db.session.add(UsernameHistory(
            user_id=user_id,
            previous_username=old_username,
            new_username=new_username,
            changed_at=datetime.utcnow(),
        ))

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


@settings_bp.route('/rename-preview', methods=['GET'])
@rate_limit(10, key_func=user_key)
def rename_preview():
    user = User.query.get(session.get('user_id'))
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)

    new_username = request.args.get('new_username', '').strip()
    if not new_username:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "new_username parameter required", status_code=400)

    try:
        _validate_rename(user, new_username)
    except ValueError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], str(e), status_code=400)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], e.message, status_code=400)

    old = user.username
    preview = {
        "messages_sent": Message.query.filter_by(sender=old).count(),
        "messages_received": Message.query.filter_by(recipient=old).count(),
        "messages_replied": Message.query.filter_by(reply_to=old).count(),
        "groups_owned": Group.query.filter_by(owner_username=old).count(),
        "group_memberships": GroupMember.query.filter_by(username=old).count(),
        "invites_sent": GroupInvite.query.filter_by(invited_by=old).count(),
        "invites_received": GroupInvite.query.filter_by(username=old).count(),
        "join_requests": GroupJoinRequest.query.filter_by(username=old).count(),
    }
    preview["total_affected"] = sum(v for k, v in preview.items())
    preview["estimated_ms"] = max(5, preview["total_affected"] // 20)
    return success_response(preview)


@settings_bp.route('/username', methods=['POST'])
@rate_limit(3, key_func=user_key)
def change_username():
    user = User.query.get(session.get('user_id'))
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)

    data = request.get_json(silent=True)
    if not data or 'new_username' not in data:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "new_username is required", status_code=400)

    new_username = data['new_username'].strip()
    old_username = user.username

    try:
        _rename_user(user.id, old_username, new_username)
    except ValueError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], str(e), status_code=400)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], e.message, status_code=400)
    except Exception as e:
        logger.exception("Rename failed for user '%s' to '%s'", old_username, new_username)
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], "Rename failed", status_code=500)

    # Post-commit runtime state updates
    session['username'] = new_username
    presence_registry.rename_user(old_username, new_username)

    # Notify all connected clients
    from flask import current_app
    sio = current_app.extensions.get('socketio')
    if sio:
        sio.emit('user_rename', {
            'old_username': old_username,
            'new_username': new_username,
        }, room='All')

    logger.info("User '%s' renamed to '%s'", old_username, new_username)
    return success_response({"username": new_username})


@settings_bp.route('/password', methods=['POST'])
@rate_limit(5, key_func=user_key)
def change_password():
    user = User.query.get(session.get('user_id'))
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)

    data = request.get_json(silent=True)
    if not data:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Request body required", status_code=400)

    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not current_password or not new_password or not confirm_password:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "current_password, new_password, and confirm_password are required", status_code=400)

    if not user.check_password(current_password):
        return error_response(ErrorCode.AUTH_INVALID_CREDENTIALS[0], "Current password is incorrect", status_code=400)

    if new_password == current_password:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "New password must be different from current password", status_code=400)

    if new_password != confirm_password:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Passwords do not match", status_code=400)

    try:
        validate_password(new_password)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_PASSWORD[0], e.message, status_code=400)

    user.set_password(new_password)
    db.session.commit()

    session.clear()
    logger.info("User '%s' changed password (session cleared)", user.username)
    return success_response({"requires_relogin": True})
