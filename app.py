import eventlet
eventlet.monkey_patch()

import os
import logging
from dotenv import load_dotenv

load_dotenv()
from flask import Flask, request
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func
from config import Config
from database.database import db
from utils.security.sanitizers import sanitize_html

log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

cors_origins = os.environ.get('CORS_ORIGIN', '*').split(',')
socketio = SocketIO(cors_allowed_origins=cors_origins)
csrf = CSRFProtect()

def background_broadcast_task(app):
    with app.app_context():
        from models.models import SystemBroadcast
        import datetime as dt
        import uuid
        while True:
            try:
                unsent = SystemBroadcast.query.filter_by(is_sent=False).all()
                for b in unsent:
                    msg_id = str(uuid.uuid4())
                    timestamp = dt.datetime.now().strftime("%H:%M")
                    safe_content = sanitize_html(b.message)
                    socketio.emit('new_message', {
                        "type": "system",
                        "sender": "Admin",
                        "to": "All",
                        "content": safe_content,
                        "time": timestamp,
                        "msg_id": msg_id
                    }, room='All')
                    b.is_sent = True
                    db.session.commit()
            except Exception as e:
                logger.error("Error in background broadcast task: %s", e)
                db.session.rollback()
            eventlet.sleep(5)

def create_app(config_class=Config):
    if not config_class.SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Set SECRET_KEY before starting the application."
        )

    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    socketio.init_app(app, manage_session=False, async_mode='eventlet')
    csrf.init_app(app)

    # Exempt Socket.IO routes from CSRF protection
    for _rule in app.url_map.iter_rules():
        if _rule.rule.startswith('/socket.io/'):
            _view = app.view_functions.get(_rule.endpoint)
            if _view:
                csrf.exempt(_view)

    from routes.auth import auth_bp
    from routes.api import api_bp
    from routes.main import main_bp
    from routes.admin import admin_bp
    from routes.migration import migration_bp
    from routes.backup_center import backup_center_bp
    from routes.settings import settings_bp

    csrf.exempt(auth_bp)
    csrf.exempt(api_bp)

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(migration_bp)
    app.register_blueprint(backup_center_bp)
    app.register_blueprint(settings_bp)

    from sockets.events import register_events
    register_events(socketio)

    @app.context_processor
    def inject_asset_helpers():
        import os
        dist_dir = os.path.join(app.static_folder, 'dist')
        use_minified = os.path.exists(os.path.join(dist_dir, 'js', 'bundle.min.js'))
        return dict(use_minified_assets=use_minified)

    with app.app_context():
        import sqlite3
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            c.fetchall()
            conn.close()
        except Exception as e:
            logger.error("Failed to check DB tables: %s", e)

        db.create_all()
        try:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN last_seen DATETIME"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN created_at DATETIME"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN is_banned BOOLEAN DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE message ADD COLUMN deleted_by_sender BOOLEAN DEFAULT 0"))
            db.session.execute(db.text("ALTER TABLE message ADD COLUMN deleted_by_recipient BOOLEAN DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE message ADD COLUMN created_at DATETIME"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE `group` ADD COLUMN description VARCHAR(255)"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN theme VARCHAR(20) DEFAULT 'system'"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN default_status VARCHAR(20) DEFAULT 'Available'"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # ── Database indexes ──────────────────────────────────────────
        # Tier 1 — unread-count batch query (runs on every connect/disconnect/status change)
        #   SELECT sender, recipient, COUNT(id) WHERE recipient IN (...) AND status != 'read'
        #   GROUP BY sender, recipient
        try:
            db.session.execute(
                db.text(
                    "CREATE INDEX IF NOT EXISTS ix_message_recipient_status_sender "
                    "ON message (recipient, status, sender)"
                )
            )
            db.session.commit()
            logger.info("Index ix_message_recipient_status_sender created/confirmed.")
        except Exception as e:
            db.session.rollback()
            logger.warning("Could not create ix_message_recipient_status_sender: %s", e)

        # Tier 2 — last-message per pair batch query
        #   SELECT MAX(id) WHERE sender IN (...) AND recipient IN (...) GROUP BY ...
        try:
            db.session.execute(
                db.text(
                    "CREATE INDEX IF NOT EXISTS ix_message_sender_recipient_id "
                    "ON message (sender, recipient, id)"
                )
            )
            db.session.commit()
            logger.info("Index ix_message_sender_recipient_id created/confirmed.")
        except Exception as e:
            db.session.rollback()
            logger.warning("Could not create ix_message_sender_recipient_id: %s", e)

        # Migrate existing deleted flags to message_visibility table
        try:
            from models.models import Message, MessageVisibility
            # Migrate sender deletions
            sender_deletes = Message.query.filter_by(deleted_by_sender=True).all()
            for m in sender_deletes:
                exists = MessageVisibility.query.filter_by(msg_id=m.msg_id, username=m.sender).first()
                if not exists:
                    db.session.add(MessageVisibility(msg_id=m.msg_id, username=m.sender))
            
            # Migrate recipient deletions (only for private chats)
            recipient_deletes = Message.query.filter_by(deleted_by_recipient=True).all()
            for m in recipient_deletes:
                if m.recipient != 'All':
                    from models.models import Group
                    is_group = Group.query.filter_by(name=m.recipient).first() is not None
                    if not is_group:
                        exists = MessageVisibility.query.filter_by(msg_id=m.msg_id, username=m.recipient).first()
                        if not exists:
                            db.session.add(MessageVisibility(msg_id=m.msg_id, username=m.recipient))
            db.session.commit()
            logger.info("Migrated message deleted flags to message_visibility table.")
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to migrate message deleted flags: %s", e)



        # Seed admin user from environment variables (skip during testing)
        if not app.config.get('TESTING'):
            try:
                from models.models import User
                admin_password_hash = os.environ.get('ADMIN_PASSWORD_HASH')
                if admin_password_hash:
                    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
                    admin_user = User.query.filter(func.lower(User.username) == func.lower(admin_username)).first()
                    if not admin_user:
                        admin_user = User(
                            username=admin_username,
                            status="Offline",
                            is_admin=True,
                            password_hash=admin_password_hash
                        )
                        db.session.add(admin_user)
                        logger.info("Admin user '%s' created.", admin_username)
                    else:
                        admin_user.is_admin = True
                        admin_user.password_hash = admin_password_hash
                        logger.info("Admin user '%s' updated.", admin_username)
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error("Failed to seed admin user: %s", e)

        # Start background task
        eventlet.spawn(background_broadcast_task, app)

        # Start background presence checker
        from utils.security.constants import PRESENCE_CHECK_INTERVAL_SECONDS
        def _run_presence_check():
            from sockets.events import check_away_users
            while True:
                eventlet.sleep(PRESENCE_CHECK_INTERVAL_SECONDS)
                try:
                    check_away_users()
                except Exception as e:
                    logger.exception("Presence check failed: %s", e)
        eventlet.spawn(_run_presence_check)

    # ── Security Response Headers ──────────────────────────────────────
    # CSP starts in Report-Only. 'unsafe-inline' is temporary technical debt
    # until internal styles/scripts are extracted to files.
    @app.after_request
    def add_security_headers(response):
        response.headers['Content-Security-Policy-Report-Only'] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'"
        )
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = (
            "camera=(), display-capture=(), geolocation=(), "
            "microphone=(self), payment=(), usb=()"
        )
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = \
                'max-age=31536000; includeSubDomains'
        return response

    return app

if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
