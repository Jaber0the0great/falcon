import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Required: set SECRET_KEY via environment variable
    SECRET_KEY = os.environ.get('SECRET_KEY')

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(BASE_DIR, 'database', 'falcon_web.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB max upload

    # Explicit DEBUG mode
    DEBUG = False

    # Session cookie security flags
    # Set SESSION_COOKIE_SECURE=false in .env for local HTTP development
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_NAME = 'falcon_session'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_REFRESH_EACH_REQUEST = True

    # TURN Server credentials for WebRTC NAT Traversal
    TURN_SERVER = os.environ.get('TURN_SERVER') or 'turn:openrelay.metered.ca:80'
    TURN_USERNAME = os.environ.get('TURN_USERNAME') or 'openrelayproject'
    TURN_CREDENTIAL = os.environ.get('TURN_CREDENTIAL') or 'openrelayproject'

    # Self-Hosted Coturn STUN/TURN configuration
    COTURN_DOMAIN = os.environ.get('COTURN_DOMAIN', 'falconchat.duckdns.org')
    COTURN_AUTH_SECRET = os.environ.get(
        'COTURN_AUTH_SECRET',
        'e7c8f2a1b9d4e3f6a8b0c2d4e6f8a0b2c4d6e8f0a2b4c6d8e0f2a4b6c8d0e2f4'
    )


