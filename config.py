import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-falcon-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'falcon_web.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB max upload

    # TURN Server credentials for WebRTC NAT Traversal (e.g. from Metered.ca or Cloudflare)
    # If calls fail between different networks, configure your own active credentials here:
    TURN_SERVER = os.environ.get('TURN_SERVER') or 'turn:openrelay.metered.ca:80'
    TURN_USERNAME = os.environ.get('TURN_USERNAME') or 'openrelayproject'
    TURN_CREDENTIAL = os.environ.get('TURN_CREDENTIAL') or 'openrelayproject'

