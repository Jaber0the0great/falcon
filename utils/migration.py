import sys
import os
import sqlite3
import uuid
from flask import Flask

# Add parent directory to path so we can import config, database, and models
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from database.database import db
from models.models import User, Message

# Local app instance for running as a standalone script
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

def migrate_db(app_instance=None):
    # Use the passed app instance or fallback to the local script app instance
    target_app = app_instance or app
    with target_app.app_context():
        db.create_all()
        
        paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chat_history.db")),
            os.path.join(os.environ.get('APPDATA', os.path.expanduser("~")), "Falcon", "chat_history.db"),
            "d:\\Downloads\\Falcon\\chat_history.db"
        ]
        
        # Remove duplicate paths while preserving order
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
                    print(f"Source DB path {p} has {count} messages.")
                    if count > max_messages:
                        max_messages = count
                        best_path = p
                except Exception as e:
                    print(f"Error checking source DB {p}: {e}")
                    
        if not best_path:
            print("No source database found in any of the searched paths.")
            return
            
        print(f"Selected source database: {best_path} with {max_messages} messages.")
        
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
                    
            print(f"Found {len(users)} unique users.")
            
            for username in users:
                if not User.query.filter_by(username=username).first():
                    u = User(username=username)
                    u.set_password("password123")  # default password
                    db.session.add(u)
            
            db.session.commit()
            
            print(f"Found {len(rows)} messages. Migrating...")
            migrated_count = 0
            for r in rows:
                keys = r.keys()
                if not r['sender'] or not r['recipient']:
                    print(f"Skipping invalid message (missing sender/recipient): msg_id={r['msg_id'] if 'msg_id' in keys else None}, type={r['msg_type'] if 'msg_type' in keys else None}")
                    continue
                    
                msg_id = r['msg_id'] if 'msg_id' in keys else None
                if not msg_id:
                    msg_id = str(uuid.uuid4())
                
                # Check if this msg already exists
                exists = False
                if 'msg_id' in keys and r['msg_id']:
                    exists = Message.query.filter_by(msg_id=r['msg_id']).first() is not None
                else:
                    # Fallback check for messages without msg_id to avoid duplicates
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
            print(f"Migration complete. Migrated {migrated_count} messages.")
            
        except Exception as e:
            print("Error migrating:", e)
        finally:
            conn.close()

if __name__ == '__main__':
    migrate_db()
