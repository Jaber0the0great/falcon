from flask import Blueprint, render_template, session, redirect
from models.models import User
from database.database import db
from utils.security import rate_limit, ip_key, PAGE_LIMIT, REGISTER_PAGE_LIMIT

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@rate_limit(PAGE_LIMIT, key_func=ip_key)
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            session['username'] = user.username
            theme = user.theme or 'system'
        else:
            session.clear()
            return redirect('/login')
        return render_template('chat.html', theme=theme)
    return redirect('/login')

@main_bp.route('/login')
@rate_limit(PAGE_LIMIT, key_func=ip_key)
def login():
    if 'user_id' in session:
        return redirect('/')
    return render_template('login.html')

@main_bp.route('/register')
@rate_limit(REGISTER_PAGE_LIMIT, key_func=ip_key)
def register():
    if 'user_id' in session:
        return redirect('/')
    return render_template('register.html')
