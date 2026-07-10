import logging
from flask import Blueprint, request, session
from models.models import User
from database.database import db

from sqlalchemy import func
from utils.security import (
    validate_username,
    validate_password,
    ValidationError,
    rate_limit,
    ip_key,
    AUTH_LOGIN_LIMIT,
    AUTH_REGISTER_LIMIT,
    AUTH_LOGOUT_LIMIT,
)
from utils.security.constants import RESERVED_USERNAMES
from utils.api import success_response, error_response, ErrorCode

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['POST'])
@rate_limit(AUTH_LOGIN_LIMIT, key_func=ip_key)
def login():
    data = request.json
    if not data:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Username and password required", status_code=400)

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Username and password required", status_code=400)

    user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
    if user and user.check_password(password):
        if user.is_banned:
            logger.warning("Banned user '%s' attempted to log in.", username)
            return error_response(ErrorCode.AUTH_ACCOUNT_BANNED[0], "Invalid username or password", status_code=401)

        session.clear()
        session['user_id'] = user.id
        session['username'] = user.username
        session.permanent = True
        user.status = "Available"
        db.session.commit()

        if user.is_admin:
            session['admin_logged_in'] = True
            return success_response({"username": user.username, "is_admin": True})
        
        return success_response({"username": user.username})
        
    return error_response(ErrorCode.AUTH_INVALID_CREDENTIALS[0], "Invalid credentials", status_code=401)

@auth_bp.route('/register', methods=['POST'])
@rate_limit(AUTH_REGISTER_LIMIT, key_func=ip_key)
def register():
    data = request.json
    if not data:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Username and password required", status_code=400)

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Username and password required", status_code=400)

    try:
        username = validate_username(username)
        validate_password(password)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], e.message, status_code=400)

    if username.lower() in RESERVED_USERNAMES:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "This username is reserved", status_code=400)

    from models.models import Group
    if User.query.filter(func.lower(User.username) == func.lower(username)).first() or \
       Group.query.filter(func.lower(Group.name) == func.lower(username)).first():
        logger.info("Registration failed: username '%s' already exists or conflicts with group name.", username)
        return error_response(ErrorCode.AUTH_USERNAME_EXISTS[0], "Registration failed", status_code=400)

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session.clear()
    session['user_id'] = user.id
    session['username'] = user.username
    return success_response({"username": user.username})

@auth_bp.route('/logout', methods=['POST'])
@rate_limit(AUTH_LOGOUT_LIMIT, key_func=ip_key)
def logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = "Offline"
            db.session.commit()
        session.clear()
    return success_response()

@auth_bp.route('/me', methods=['GET'])
@rate_limit(30, key_func=ip_key)
def get_me():
    if 'user_id' in session:
        return success_response({"logged_in": True, "username": session['username']})
    return success_response({"logged_in": False})
