# Release Checklist — Falcon Web Chat v1.0

> Use this checklist sequentially. Complete each block before starting the next.
> All checks must pass before marking the release as ready.

---

## Phase 0: Prerequisites

- [ ] **Source code** committed to a clean `main` branch
- [ ] **Git tag** applied (`v1.0.0`)
- [ ] **All sensitive files** excluded by `.gitignore` (`.env`, `*.db`, `instance/`, `static/uploads/*`)
- [ ] **No secrets** in the repository (run `git secrets --scan` or equivalent)
- [ ] **Dependency audit** performed (`pip-audit` or equivalent)
- [ ] **License** file present (if open-source)
- [ ] **README** updated with install/run instructions

## Phase 1: Required Environment Variables

- [ ] **`SECRET_KEY`** generated (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- [ ] **`ENCRYPTION_KEY`** generated (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- [ ] **`ADMIN_PASSWORD_HASH`** generated (`python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"`)
- [ ] `ADMIN_USERNAME` set (optional, defaults to `admin`)
- [ ] `CORS_ORIGIN` set to the deployment domain
- [ ] `LOG_LEVEL` set to `WARNING` or `ERROR` in production
- [ ] `TURN_SERVER` / `TURN_USERNAME` / `TURN_CREDENTIAL` configured for production TURN relay

## Phase 2: Infrastructure

### Database
- [ ] **PostgreSQL** provisioned (SQLite is NOT suitable for production)
- [ ] Connection string set via `SQLALCHEMY_DATABASE_URI`
- [ ] Connection pool size configured (min 2, max 10 recommended)
- [ ] Startup migration tested against empty database
- [ ] Startup migration tested against existing database (no data loss)
- [ ] Database backups configured (daily at minimum)

### TLS / HTTPS
- [ ] TLS certificate obtained and configured (Let's Encrypt or cloud LB)
- [ ] `SESSION_COOKIE_SECURE = True` (already set — confirm working over TLS)
- [ ] `X-Forwarded-Proto` header trusted from reverse proxy
- [ ] HSTS header confirmed present on HTTPS responses
- [ ] HTTP-to-HTTPS redirect configured
- [ ] `Strict-Transport-Security` max-age set (31536000 for production)

### Reverse Proxy (nginx / Cloudflare / LB)
- [ ] Proxy passes `Host`, `X-Forwarded-For`, `X-Forwarded-Proto` headers
- [ ] WebSocket upgrade path configured (`Upgrade`, `Connection` headers)
- [ ] Static file caching configured (`/static/` with far-future expires)
- [ ] File upload size limit aligned (client max body size >= 100 MB)
- [ ] Rate limiting at proxy level (100 req/s per IP recommended)
- [ ] gzip compression enabled for text assets

### Deployment Container
- [ ] `Dockerfile` created (Python 3.12 slim, pip install, eventlet worker)
- [ ] `.dockerignore` excludes `*.db`, `.env`, `__pycache__`, `.git`
- [ ] Container health check endpoint (`/` returns 200)
- [ ] Container runs as non-root user
- [ ] Readiness probe configured
- [ ] Liveness probe configured
- [ ] Resource limits set (CPU, memory)
- [ ] Persistent volume for `static/uploads/` (if file uploads required)
- [ ] Persistent volume for database (if using SQLite — NOT recommended)

### CI/CD Pipeline
- [ ] Tests run automatically on every PR/merge to main
- [ ] Security scan (SAST) runs in CI
- [ ] Dependency vulnerability check in CI
- [ ] Build produces tagged Docker image
- [ ] Deployment to staging on merge to main
- [ ] Deployment to production on release tag
- [ ] Rollback procedure documented

## Phase 3: Pre-Deployment

### Code Checks
- [ ] All 15 unit tests pass
- [ ] Manual upload tests pass (if environment available)
- [ ] Lint check passes (ruff or equivalent)
- [ ] `ENCRYPTION_KEY` validation: App starts without it but fails on first message — confirm production env has it set
- [ ] `SECRET_KEY` validation: App **refuses to start** without it — verified
- [ ] Confirm `SESSION_COOKIE_SECURE = True` in production config
- [ ] Confirm `DEBUG = False` in production config
- [ ] Confirm `CORS_ORIGIN` is set to production domain (not `*`)
- [ ] Confirm `ALLOWED_EXTENSIONS` matches business requirements
- [ ] Confirm `MAX_CONTENT_LENGTH` and `MAX_UPLOAD_SIZE` are aligned

### Security Checks
- [ ] **CSRF protection** enabled (Flask-WTF) — confirmed present
- [ ] **CSP Report-Only** header present on all routes — confirmed
- [ ] **All 8 security response headers** verified:
  - `Content-Security-Policy-Report-Only`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy` (microphone only)
  - `Cross-Origin-Opener-Policy: same-origin`
  - `Cross-Origin-Resource-Policy: same-origin`
  - `Strict-Transport-Security` (only over HTTPS)
- [ ] CSRF token injection via `csrf.js` — confirmed
- [ ] Socket.IO CSRF exemption — confirmed (explicitly exempted from Flask-WTF)
- [ ] No `'unsafe-eval'` in CSP — confirmed
- [ ] No hardcoded secrets in codebase — confirmed
- [ ] `sanitize_html()` applied to all user-originated content — confirmed
- [ ] File upload validation (5 layers) — confirmed
- [ ] Login brute-force protection not yet implemented — **RISK ACCEPTED**
- [ ] Rate limiting on login/register not yet implemented — **RISK ACCEPTED**
- [ ] Download endpoint access control not yet implemented — **RISK ACCEPTED** (UUID mitigation in place)
- [ ] Admin action audit logging not yet implemented — **RISK ACCEPTED**
- [ ] SRI (Subresource Integrity) for CDN resources not yet implemented — **RISK ACCEPTED**

## Phase 4: Deployment

- [ ] Application deployed to target environment
- [ ] All required environment variables set
- [ ] Database migrations applied successfully
- [ ] Static files accessible
- [ ] Application responds to health check
- [ ] WebSocket connections established
- [ ] File uploads directory writable

## Phase 5: Post-Deployment Verification

### Critical Paths
- [ ] **Login** — valid users can log in, invalid get rejected
- [ ] **Registration** — new users can register, duplicate usernames rejected
- [ ] **Logout** — session cleared, redirect to login
- [ ] **Send message** — text messages delivered to recipient
- [ ] **Receive message** — messages appear in real-time
- [ ] **File upload** — files uploaded, displayed, downloadable
- [ ] **WebRTC call** — peer-to-peer audio call establishes
- [ ] **Group creation** — groups created with members
- [ ] **Group messaging** — messages broadcast to all members
- [ ] **Admin dashboard** — accessible at `/admin/`
- [ ] **Admin broadcast** — system message sent to all users

### Edge Cases
- [ ] **Banned user cannot log in** — returns generic error
- [ ] **Non-existent user cannot log in** — returns generic error
- [ ] **Group owner cannot leave group** — must delete
- [ ] **File upload with double extension** — rejected
- [ ] **File too large** — rejected with 413
- [ ] **CSRF token missing** — request rejected with 400
- [ ] **Session expired** — user redirected to login
- [ ] **Message to banned user** — handled gracefully

### Security Headers (in production)
- [ ] All 8 headers present on `GET /`
- [ ] All 8 headers present on `GET /login`
- [ ] All 8 headers present on `GET /register`
- [ ] All 8 headers present on `POST /auth/login`
- [ ] All 8 headers present on `GET /api/webrtc_config`
- [ ] All 8 headers present on 404 error page
- [ ] HSTS present only over HTTPS (absent on HTTP)
- [ ] Socket.IO polling endpoint: headers absent (known limitation, non-executable response)
- [ ] No CSP violations in browser DevTools console

### Performance Validation
- [ ] Page load time < 3s (cold start)
- [ ] Message delivery latency < 500ms (p95)
- [ ] File upload (10 MB) completes within 30s
- [ ] 50 concurrent users connected without errors
- [ ] Database query count per page load < 20

## Phase 6: Monitoring & Operations

### Logging
- [ ] Application logs shipped to aggregation service
- [ ] Log level set to `WARNING` in production
- [ ] Error alerts configured (500 errors, crash loops)
- [ ] Failed login attempts logged with source IP
- [ ] Admin actions logged with timestamp and username
- [ ] File uploads logged with filename, size, user

### Metrics
- [ ] Health check endpoint monitored (every 30s)
- [ ] CPU/memory usage monitored
- [ ] Database connection pool utilization monitored
- [ ] Disk usage monitored (uploads + database)
- [ ] Active user count tracked over time
- [ ] Message throughput tracked (messages/minute)
- [ ] WebSocket connection count tracked
- [ ] File upload count/size tracked

### Alerts
- [ ] Application unreachable (HTTP 5xx > 1% over 5 min)
- [ ] Database connection pool exhausted
- [ ] Disk usage > 80%
- [ ] Certificate expiry < 30 days
- [ ] Memory usage > 85%
- [ ] Crash loop detected (restarts > 3 in 5 min)

## Known Limitations (Documented, Accepted for v1.0)

| # | Limitation | Impact | Mitigation |
|---|---|---|---|
| 1 | SQLite in development, PostgreSQL recommended | Concurrent write performance | Use PostgreSQL in production |
| 2 | No brute force protection on login | Credential brute force possible | Rate limit at reverse proxy level |
| 3 | No magic-byte file validation | Advisory MIME check only | Extension allowlist is primary defense |
| 4 | CSP in Report-Only mode | Violations not blocked | Monitor console, fix for v1.1 |
| 5 | Socket.IO lacks security headers | Non-executable content only | Low risk |
| 6 | No admin audit log | Admin actions untracked | Accept for internal tool |
| 7 | No SRI on CDN resources | CDN compromise possible | Use pinned CDN versions |
| 8 | Message encryption key in env var | Not ideal for key mgmt | Consider KMS/vault in future |

## Sign-off

- [ ] **QA** — All checklist items verified
- [ ] **Security** — Risks documented and accepted
- [ ] **Engineering** — Release artifacts built and tested
- [ ] **Product** — Feature completeness confirmed
- [ ] **Release date:** ____________________
- [ ] **Release manager:** ____________________
