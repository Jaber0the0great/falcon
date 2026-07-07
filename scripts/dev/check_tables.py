import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'database', 'falcon_web.db')
conn = sqlite3.connect(db_path)
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
logger.info([t[0] for t in tables])
conn.close()
