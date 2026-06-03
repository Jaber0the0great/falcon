from flask import Blueprint, request, jsonify, session
from models.models import User
from database.database import db

from sqlalchemy import func
auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required"}), 400

    # Intercept admin credentials
    if username.strip().lower() == 'admin' and password == 'jaber142005':
        session.clear()
        session['admin_logged_in'] = True
        session['username'] = 'admin'
        return jsonify({"success": True, "username": "admin", "is_admin": True})
        
    user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
    if user and user.check_password(password):
        if user.is_banned:
            return jsonify({"success": False, "error": "Your account has been banned by the administrator."}), 403
            
        session['user_id'] = user.id
        session['username'] = user.username
        user.status = "Available"
        db.session.commit()
        return jsonify({"success": True, "username": user.username})
        
    return jsonify({"success": False, "error": "Invalid credentials"}), 401

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password required"}), 400
        
    if User.query.filter(func.lower(User.username) == func.lower(username)).first():
        return jsonify({"success": False, "error": "Username already exists"}), 400
        
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    session['user_id'] = user.id
    session['username'] = user.username
    return jsonify({"success": True, "username": user.username})

@auth_bp.route('/logout', methods=['POST'])
def logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = "Offline"
            db.session.commit()
        session.clear()
    return jsonify({"success": True})

@auth_bp.route('/me', methods=['GET'])
def get_me():
    if 'user_id' in session:
        return jsonify({"logged_in": True, "username": session['username']})
    return jsonify({"logged_in": False})
