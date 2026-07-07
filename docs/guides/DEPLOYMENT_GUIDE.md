# Deployment Guide — Falcon Web Chat v1.0

## Architecture Overview

```
Internet
    │
    ▼
[ TLS Termination ]   ← Cloudflare LB / nginx / Caddy
    │
    ▼
[ Reverse Proxy ]     ← nginx — routes /socket.io/ WebSocket upgrades
    │
    ▼
[ Flask App ]         ← eventlet async worker, single process
    │
    ├── PostgreSQL     ← (preferred) or SQLite
    └── static/uploads ← persistent volume
```

**Important:** The app uses **eventlet** (async single-process model). Do NOT use multiple gunicorn workers — eventlet handles concurrency within one process. For multi-worker deployments, the in-memory Socket.IO rate limiter and session store must be replaced with Redis.

---

## 1. Environment Variables

### Required
| Variable | Description | How to Generate |
|---|---|---|
| `SECRET_KEY` | Flask session signing key, 32+ bytes | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENCRYPTION_KEY` | Fernet key for message encryption | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ADMIN_PASSWORD_HASH` | Werkzeug hash of admin password | `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"` |

### Important Notes
- If `SECRET_KEY` changes, ALL existing sessions become invalid (users logged out).
- If `ENCRYPTION_KEY` changes, ALL existing encrypted messages become unreadable.
- `ADMIN_PASSWORD_HASH` is optional — if not set, no admin user is created on startup.
- `ENCRYPTION_KEY` is not checked at startup — the app will start but fail with `RuntimeError` on the first message send/decrypt.

### Optional
| Variable | Default | Description |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Admin account username |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CORS_ORIGIN` | `*` | Comma-separated allowed CORS origins |
| `TURN_SERVER` | `turn:openrelay.metered.ca:80` | TURN server for WebRTC |
| `TURN_USERNAME` | `openrelayproject` | TURN username |
| `TURN_CREDENTIAL` | `openrelayproject` | TURN credential |
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///falcon_web.db` | Database connection string |

### Production .env Example
```bash
SECRET_KEY=your-64-char-hex-string
ENCRYPTION_KEY=your-44-char-base64-fernet-key
ADMIN_PASSWORD_HASH=pbkdf2:sha256:600000$salt$hash
ADMIN_USERNAME=admin
LOG_LEVEL=WARNING
CORS_ORIGIN=https://falcon.example.com
TURN_SERVER=turn:your-turn-server.com:3478
TURN_USERNAME=your-turn-username
TURN_CREDENTIAL=your-turn-credential
SQLALCHEMY_DATABASE_URI=postgresql://user:pass@host:5432/falcon
```

---

## 2. Database

### Production: PostgreSQL (Recommended)
```python
# config.py (production override)
SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI')
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 5,
    'max_overflow': 10,
    'pool_timeout': 30,
    'pool_recycle': 1800,
}
```

### Migration from SQLite to PostgreSQL
The app uses **startup migrations** (`ALTER TABLE` in try/except blocks). These are safe for SQLite but may fail on PostgreSQL with type differences. Recommended approach:

1. Export data from SQLite:
   ```bash
   sqlite3 falcon_web.db .dump > backup.sql
   ```
2. Set up PostgreSQL database and connection string
3. Start the app — `db.create_all()` creates the schema
4. Import data (with schema adjustments as needed)
5. Verify data integrity
6. Test all flows

### Startup Migrations (Current)
The application runs these migrations on every startup:
- `ALTER TABLE user ADD COLUMN last_seen DATETIME`
- `ALTER TABLE user ADD COLUMN created_at DATETIME`
- `ALTER TABLE user ADD COLUMN is_banned BOOLEAN DEFAULT 0`
- `ALTER TABLE message ADD COLUMN deleted_by_sender BOOLEAN DEFAULT 0`
- `ALTER TABLE message ADD COLUMN deleted_by_recipient BOOLEAN DEFAULT 0`
- `ALTER TABLE message ADD COLUMN created_at DATETIME`
- `ALTER TABLE `group` ADD COLUMN description VARCHAR(255)`
- `ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0`
- `CREATE INDEX IF NOT EXISTS ix_message_recipient_status_sender ...`
- `CREATE INDEX IF NOT EXISTS ix_message_sender_recipient_id ...`

These are **idempotent** with SQLite (try/except). With PostgreSQL, verify the column/index does not already exist before running.

---

## 3. Docker Deployment

### Dockerfile
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for eventlet + audio
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create uploads directory with proper permissions
RUN mkdir -p static/uploads && chown -R appuser:appuser static/uploads

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')"

EXPOSE 5000

CMD ["python", "app.py"]
```

### docker-compose.yml (Production)
```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
      - ADMIN_PASSWORD_HASH=${ADMIN_PASSWORD_HASH}
      - CORS_ORIGIN=${CORS_ORIGIN}
      - LOG_LEVEL=WARNING
      - SQLALCHEMY_DATABASE_URI=postgresql://falcon:password@db:5432/falcon
      - TURN_SERVER=${TURN_SERVER}
      - TURN_USERNAME=${TURN_USERNAME}
      - TURN_CREDENTIAL=${TURN_CREDENTIAL}
    volumes:
      - uploads:/app/static/uploads
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: falcon
      POSTGRES_USER: falcon
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U falcon"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - app
    restart: unless-stopped

volumes:
  pgdata:
  uploads:
```

### nginx.conf
```nginx
upstream falcon_app {
    server app:5000;
}

server {
    listen 80;
    server_name falcon.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name falcon.example.com;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Static files with caching
    location /static/ {
        alias /app/static/;
        expires 365d;
        add_header Cache-Control "public, immutable";
    }

    # Uploaded files (served by app for access control)
    location /api/download/ {
        proxy_pass http://falcon_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support for Socket.IO
    location /socket.io/ {
        proxy_pass http://falcon_app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # Main app
    location / {
        proxy_pass http://falcon_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Security headers (add those not already set by the app)
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

---

## 4. Railway Deployment

### railway.json
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt"
  },
  "deploy": {
    "startCommand": "python app.py",
    "healthcheckPath": "/",
    "healthcheckTimeout": 10,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

### Railway Steps
1. Connect GitHub repository to Railway
2. Set all required environment variables in Railway dashboard
3. Add PostgreSQL plugin (update `SQLALCHEMY_DATABASE_URI`)
4. Deploy
5. Add custom domain with TLS

---

## 5. Manual Deployment (Bare Metal / VPS)

### Prerequisites
```bash
# System dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx certbot postgresql

# Clone repository
git clone https://github.com/yourorg/falcon-web-chat.git /opt/falcon
cd /opt/falcon

# Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create uploads directory
mkdir -p static/uploads
chown -R www-data:www-data static/uploads
```

### Systemd Service
```ini
# /etc/systemd/system/falcon.service
[Unit]
Description=Falcon Web Chat
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/falcon
EnvironmentFile=/opt/falcon/.env
ExecStart=/opt/falcon/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable falcon
sudo systemctl start falcon
```

---

## 6. Database Migration Checklist

| Step | Command / Action |
|---|---|
| 1. Backup production DB | `pg_dump falcon > falcon_backup_$(date +%Y%m%d).sql` |
| 2. Deploy new code | Pull, build, restart |
| 3. Run migrations | Automatic on startup (try/except) |
| 4. Verify schema | `python check_tables.py` |
| 5. Seed admin user | Automatic if `ADMIN_PASSWORD_HASH` is set |
| 6. Test core flows | Login, message, upload, admin |
| 7. Verify indexes | `\di` in psql — confirm `ix_message_*` indexes exist |
| 8. Monitor errors | Check application logs after migration |

---

## 7. Rollback Procedure

```bash
# 1. Revert code
git checkout v0.9.0

# 2. Restore database
pg_restore --clean --if-exists -d falcon falcon_backup_20250101.sql

# 3. Restart application
sudo systemctl restart falcon

# 4. Verify rollback
curl -f https://falcon.example.com/ && echo "OK"
```

---

## 8. Security Checklist Before Going Live

- [ ] All required env vars set (not default/placeholder values)
- [ ] TLS certificate valid and auto-renewal configured
- [ ] `CORS_ORIGIN` set to specific domain (not `*`)
- [ ] `LOG_LEVEL` set to `WARNING` in production
- [ ] Debug mode disabled (`FLASK_DEBUG=0`)
- [ ] File upload directory not publicly accessible
- [ ] Database connection uses strong credentials
- [ ] Reverse proxy limits request body size (max 100 MB)
- [ ] Rate limiting configured at reverse proxy level
- [ ] All 8 security headers verified via curl
- [ ] WebSocket upgrade path confirmed working
- [ ] No default/weak passwords in admin accounts
