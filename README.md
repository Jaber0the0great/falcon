# Falcon Web Chat

A real-time messaging application with end-to-end encryption, group chat, voice/video calls, and file sharing. Built with Flask, Socket.IO, and WebRTC.

## Features

- **Real-time messaging** — Instant message delivery via WebSocket (Socket.IO)
- **Group chat** — Create groups, invite members, manage join requests
- **Voice & video calls** — WebRTC-based peer-to-peer calls with TURN relay support
- **File sharing** — Upload and share images, audio, video, documents, and archives
- **Message reactions** — React to messages with emoji
- **Message encryption** — Messages encrypted at rest using Fernet (AES-128-CBC + HMAC)
- **Message deletion** — Delete for yourself or everyone
- **Typing indicators** — See when others are typing
- **Read receipts** — Message delivery and read status
- **User presence** — Online/offline/busy status with last-seen timestamps
- **Admin dashboard** — Web-based admin panel for user, group, message, and media management
- **Desktop admin app** — Optional PyQt6-based desktop administration tool
- **System broadcasts** — Admin can broadcast messages to all users

## Screenshots

> Screenshots will be added after the first release.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, Flask 3.0 |
| Real-time | Flask-SocketIO 5.3 (WebSocket with eventlet) |
| Database | SQLAlchemy with SQLite (PostgreSQL recommended for production) |
| Encryption | Fernet (AES-128-CBC + HMAC) via `cryptography` |
| Frontend | Vanilla JavaScript, Bootstrap 5, Bootstrap Icons |
| WebRTC | Google STUN + configurable TURN relay |
| CSRF | Flask-WTF with automatic token injection |
| Desktop Admin | PyQt6 (optional, separate application) |

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Browser     │◄───►│  Flask App        │◄───►│  SQLite/      │
│  (JS client) │     │  (eventlet async) │     │  PostgreSQL   │
│              │     │                   │     │              │
│  Socket.IO   │◄───►│  Socket.IO        │     │  Uploads/    │
│  WebRTC      │     │  WebRTC Signaling │     │  static/     │
└─────────────┘     └──────────────────┘     └──────────────┘
                           │
                    ┌──────┴──────┐
                    │  Frontend   │
                    │  Reverse    │
                    │  Proxy      │
                    │  (nginx)    │
                    └─────────────┘
```

## Folder Structure

```
falcon-web-chat/
├── app.py                      # Application factory, startup, middleware
├── config.py                   # Configuration (env vars, session, uploads)
├── version.py                  # Centralized version string
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── .gitignore
├── CHANGELOG.md
├── README.md
├── DEPLOYMENT_GUIDE.md         # Deployment instructions
├── KEY_ROTATION.md             # Encryption key rotation guide
│
├── database/
│   └── database.py             # SQLAlchemy database instance
│
├── models/
│   └── models.py               # ORM models (User, Message, Group, etc.)
│
├── routes/
│   ├── auth.py                 # Authentication endpoints (/auth/*)
│   ├── api.py                  # Core API endpoints (/api/*)
│   ├── admin.py                # Admin API endpoints (/admin/api/*)
│   └── main.py                 # Page routes (/, /login, /register)
│
├── sockets/
│   └── events.py               # Socket.IO event handlers
│
├── utils/
│   ├── __init__.py
│   ├── crypto.py               # Fernet encryption helpers
│   ├── api/
│   │   ├── __init__.py
│   │   ├── response.py         # success_response(), error_response()
│   │   └── errors.py           # ErrorCode enum
│   └── security/
│       ├── __init__.py
│       ├── constants.py        # Rate limits, patterns, messages
│       ├── validators.py       # Username, password, group validators
│       ├── sanitizers.py       # HTML sanitization, filename sanitization
│       ├── decorators.py       # @login_required, @admin_required
│       ├── permissions.py      # Group ownership/membership helpers
│       ├── rate_limiter.py     # In-memory sliding window rate limiter
│       └── exceptions.py       # Custom exception hierarchy
│
├── templates/
│   ├── base.html               # Base layout with CSRF token
│   ├── chat.html               # Main chat interface
│   ├── login.html              # Login page
│   ├── register.html           # Registration page
│   └── admin/
│       └── admin_dashboard.html # Admin panel
│
├── static/
│   ├── css/style.css           # Application styles
│   ├── js/
│   │   ├── app.js              # Main application logic
│   │   ├── csrf.js             # CSRF token auto-injection
│   │   ├── socket.js           # Socket.IO client
│   │   └── webrtc.js           # WebRTC call handling
│   ├── audio/                  # Notification sounds
│   └── uploads/                # User-uploaded files
│
├── admin_app.py                # Desktop admin app (PyQt6, optional)
├── test_web_app.py             # Unit tests (15 tests)
├── encrypt_migration.py        # Message encryption migration script
├── benchmark_broadcast.py      # Broadcast performance benchmark
│
└── *.md                        # Documentation (25+ documents)
```

## Installation

### Prerequisites

- Python 3.12+
- pip

### Setup

```bash
# Clone the repository
git clone https://github.com/yourorg/falcon-web-chat.git
cd falcon-web-chat

# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env from template
cp .env.example .env

# Generate required secrets (edit .env after)
python -c "import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(32)}')"
python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')"
python -c "from werkzeug.security import generate_password_hash; print(f'ADMIN_PASSWORD_HASH={generate_password_hash(\"your-admin-password\")}')"

# Run the application
python app.py
```

Open `http://localhost:5000` in your browser.

## Environment Variables

### Required

| Variable | Description | Generate With |
|---|---|---|
| `SECRET_KEY` | Flask session signing key (32+ bytes) | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENCRYPTION_KEY` | Fernet key for message encryption | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ADMIN_PASSWORD_HASH` | Werkzeug hash of admin password | `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"` |

### Optional

| Variable | Default | Description |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Admin account username |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `CORS_ORIGIN` | `*` | Comma-separated allowed CORS origins |
| `TURN_SERVER` | `turn:openrelay.metered.ca:80` | TURN server for WebRTC NAT traversal |
| `TURN_USERNAME` | `openrelayproject` | TURN server username |
| `TURN_CREDENTIAL` | `openrelayproject` | TURN server credential |
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///falcon_web.db` | Database connection string |

## Railway Deployment

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#4-railway-deployment) for full instructions.

Quick start:
1. Connect your GitHub repository to Railway
2. Set all required environment variables in the Railway dashboard
3. Add the PostgreSQL plugin (update `SQLALCHEMY_DATABASE_URI`)
4. Deploy
5. Add a custom domain with TLS

## Security Features

| Feature | Status |
|---|---|
| **CSRF Protection** | Flask-WTF with automatic token injection on all same-origin fetch requests |
| **XSS Prevention** | Server-side HTML sanitization on all message/broadcast content + client-side `escapeHtml()` at all DOM sinks |
| **Rate Limiting** | 38+ HTTP endpoints (3-30 req/min) + 13 Socket.IO events (3-30 req/sec) — in-memory sliding window |
| **Message Encryption** | Fernet (AES-128-CBC + HMAC) with key rotation via `MultiFernet` |
| **Session Security** | HttpOnly + Secure + SameSite=Lax cookies, 24h expiry, regeneration on auth |
| **Security Headers** | CSP (Report-Only), HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP |
| **File Upload** | Extension whitelist (40+ types), UUID rename, size limits, path traversal prevention, MIME advisory check |
| **Secrets Management** | All secrets from environment variables; fail-fast on missing critical keys |
| **Authorization** | Admin `before_request` hook, group ownership verification, group membership checks |
| **WebRTC Security** | Server-side sender override on signaling, room isolation for group calls |
| **Account Protection** | Rate-limited login (5/min), generic error messages to prevent enumeration |

## Testing

```bash
python -m unittest test_web_app.py -v
```

Runs 15 tests covering authentication, message history, group operations, admin API, and call logging.

## Future Roadmap

### v1.1 (Short-term)
- CSP enforcement (move from Report-Only)
- Subresource Integrity on CDN resources
- Brute force account lockout
- Structured audit logging
- Magic byte file validation
- Password reset with session invalidation
- bcrypt/argon2 password hashing

### v1.2 (Medium-term)
- PostgreSQL as default database
- Docker + CI/CD pipeline
- Redis-based distributed rate limiting
- Load balancing support
- File access control (per-user authorization)

### v2.0 (Long-term)
- End-to-end encryption
- Mobile app (React Native / Flutter)
- Message search / full-text search
- File sharing with signed URLs

## License

This project is licensed under the MIT License — see the LICENSE file for details.
