from database.database import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    status = db.Column(db.String(50), default='Available')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(80), nullable=False)
    recipient = db.Column(db.String(80), nullable=False)
    msg_type = db.Column(db.String(50), nullable=False) # text, file, voice
    content = db.Column(db.Text, nullable=True)
    time = db.Column(db.String(50), nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    raw_data = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='sent')
    msg_id = db.Column(db.String(100), unique=True, nullable=False)
    reactions = db.Column(db.Text, default='{}')
    reply_to = db.Column(db.String(80), nullable=True)
    reply_content = db.Column(db.Text, nullable=True)
    deleted_by_sender = db.Column(db.Boolean, default=False, nullable=False)
    deleted_by_recipient = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    owner_username = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(80), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class GroupInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(80), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(50), default='pending') # pending, accepted, rejected
    invited_by = db.Column(db.String(80), nullable=False)

class GroupJoinRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(80), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(50), default='pending') # pending, accepted, rejected

class SystemBroadcast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_sent = db.Column(db.Boolean, default=False, nullable=False)

