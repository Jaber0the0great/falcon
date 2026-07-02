import os
from app import create_app
from database.database import db

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'falcon_web.db')

if os.path.exists(db_path):
    print(f"Removing existing database file: {db_path}")
    try:
        os.remove(db_path)
        print("Database file deleted successfully.")
    except Exception as e:
        print(f"Error deleting database file: {e}")
else:
    print("Database file does not exist.")

print("Initializing fresh database tables...")
app = create_app()
with app.app_context():
    db.create_all()
    print("Fresh database created successfully.")
