import os
import logging
from app import create_app
from database.database import db

logger = logging.getLogger(__name__)

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'database', 'falcon_web.db')

if os.path.exists(db_path):
    logger.info("Removing existing database file: %s", db_path)
    try:
        os.remove(db_path)
        logger.info("Database file deleted successfully.")
    except Exception as e:
        logger.error("Error deleting database file: %s", e)
else:
    logger.info("Database file does not exist.")

logger.info("Initializing fresh database tables...")
app = create_app()
with app.app_context():
    db.create_all()
    logger.info("Fresh database created successfully.")
