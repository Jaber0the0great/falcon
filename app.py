import eventlet
eventlet.monkey_patch()
import os
from flask import Flask
from flask_socketio import SocketIO
from config import Config
from database.database import db

socketio = SocketIO(cors_allowed_origins="*")

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
                    socketio.emit('new_message', {
                        "type": "system",
                        "sender": "Admin",
                        "to": "All",
                        "content": b.message,
                        "time": timestamp,
                        "msg_id": msg_id
                    }, room='All')
                    b.is_sent = True
                    db.session.commit()
            except Exception as e:
                print("Error in background broadcast task:", e)
                db.session.rollback()
            eventlet.sleep(5)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    socketio.init_app(app, manage_session=False, async_mode='eventlet')

    from routes.auth import auth_bp
    from routes.api import api_bp
    from routes.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(main_bp)

    from sockets.events import register_events
    register_events(socketio)

    with app.app_context():
        import os, sqlite3
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        print("DATABASE URI IN APP:", app.config['SQLALCHEMY_DATABASE_URI'])
        print("DATABASE ABSPATH:", os.path.abspath(db_path))
        print("DATABASE FILE SIZE:", os.path.getsize(db_path) if os.path.exists(db_path) else -1)
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            print("TABLES IN DB ON STARTUP:", c.fetchall())
            conn.close()
        except Exception as e:
            print("ERROR CHECKING DB TABLES:", e)

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


        # Database auto-migration disabled per user request to keep web DB independent of desktop DB.


        # Reset all users to Offline on startup
        try:
            from models.models import User
            User.query.update({User.status: 'Offline'})
            db.session.commit()
            print("Successfully reset all user statuses to Offline on startup.")
        except Exception as e:
            db.session.rollback()
            print("Failed to reset user statuses on startup:", e)

        # Start background task
        eventlet.spawn(background_broadcast_task, app)

    return app

if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)