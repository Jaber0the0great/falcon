from flask import Blueprint, render_template, session, redirect
from models.models import User
from database.database import db

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            session['username'] = user.username
        else:
            session.clear()
            return redirect('/login')
        return render_template('chat.html')
    return redirect('/login')

@main_bp.route('/login')
def login():
    if 'user_id' in session:
        return redirect('/')
    return render_template('login.html')

@main_bp.route('/register')
def register():
    if 'user_id' in session:
        return redirect('/')
    return render_template('register.html')
