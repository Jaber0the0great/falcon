import warnings
warnings.warn(
    "DEPRECATED: This module is replaced by the 'utils/migration/' package. "
    "Use 'python -m scripts.migrations.legacy_import' instead.",
    DeprecationWarning,
    stacklevel=2,
)

import sys
import os
import sqlite3
import uuid
import logging
from flask import Flask

logger = logging.getLogger(__name__)

from config import Config
from database.database import db
from models.models import User, Message

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


def migrate_db(app_instance=None):
    target_app = app_instance or app
    with target_app.app_context():
        db.create_all()

        paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chat_history.db")),
            os.path.join(os.environ.get('APPDATA', os.path.expanduser("~")), "Falcon", "chat_history.db"),
            "d:\\Downloads\\Falcon\\chat_history.db"
        ]

        unique_paths = []
        for p in paths:
            p_abs = os.path.abspath(p)
            if p_abs not in unique_paths:
                unique_paths.append(p_abs)

        best_path = None
        max_messages = -1
        for p in unique_paths:
            if os.path.exists(p):
                try:
                    conn = sqlite3.connect(p)
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) FROM messages")
                    count = c.fetchone()[0]
                    conn.close()
                    logger.info("Source DB path %s has %s messages.", p, count)
                    if count > max_messages:
                        max_messages = count
                        best_path = p
                except Exception as e:
                    logger.error("Error checking source DB %s: %s", p, e)

        if not best_path:
            logger.warning("No source database found in any of the searched paths.")
            return

        logger.info("Selected source database: %s with %s messages.", best_path, max_messages)

        conn = sqlite3.connect(best_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM messages")
            rows = cursor.fetchall()

            users = set()
            for r in rows:
                if r['sender'] and r['sender'] != 'Server':
                    users.add(r['sender'])
                if r['recipient'] and r['recipient'] not in ('All', 'Server'):
                    users.add(r['recipient'])

            logger.info("Found %s unique users.", len(users))

            for username in users:
                if not User.query.filter_by(username=username).first():
                    u = User(username=username)
                    u.set_password("password123")
                    db.session.add(u)

            db.session.commit()

            logger.info("Found %s messages. Migrating...", len(rows))
            migrated_count = 0
            for r in rows:
                keys = r.keys()
                if not r['sender'] or not r['recipient']:
                    logger.warning("Skipping invalid message (missing sender/recipient): msg_id=%s, type=%s",
                                   r['msg_id'] if 'msg_id' in keys else None,
                                   r['msg_type'] if 'msg_type' in keys else None)
                    continue

                msg_id = r['msg_id'] if 'msg_id' in keys else None
                if not msg_id:
                    msg_id = str(uuid.uuid4())

                exists = False
                if 'msg_id' in keys and r['msg_id']:
                    exists = Message.query.filter_by(msg_id=r['msg_id']).first() is not None
                else:
                    exists = Message.query.filter_by(
                        sender=r['sender'],
                        recipient=r['recipient'],
                        content=r['content'],
                        time=r['time']
                    ).first() is not None

                if not exists:
                    msg = Message(
                        sender=r['sender'],
                        recipient=r['recipient'],
                        msg_type=r['msg_type'] if 'msg_type' in keys else 'text',
                        content=r['content'] if 'content' in keys else None,
                        time=r['time'] if 'time' in keys else None,
                        duration=r['duration'] if 'duration' in keys else None,
                        file_name=r['file_name'] if 'file_name' in keys else None,
                        raw_data=r['raw_data'] if 'raw_data' in keys else None,
                        status=r['status'] if 'status' in keys else 'sent',
                        msg_id=msg_id,
                        reactions=r['reactions'] if 'reactions' in keys else '{}',
                        reply_to=r['reply_to'] if 'reply_to' in keys else None,
                        reply_content=r['reply_content'] if 'reply_content' in keys else None
                    )
                    db.session.add(msg)
                    migrated_count += 1

            db.session.commit()
            logger.info("Migration complete. Migrated %s messages.", migrated_count)

        except Exception as e:
            logger.error("Error migrating: %s", e)
        finally:
            conn.close()


if __name__ == '__main__':
    print("WARNING: This CLI is deprecated. Use 'python -m scripts.migrations.legacy_import' instead.")
    migrate_db()
