# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-04

### Added

- **Security**: CSRF protection via Flask-WTF with automatic token injection (`csrf.js`)
- **Security**: Rate limiting on all 38+ HTTP endpoints (login 5/min, register 3/min, upload 6/min, etc.)
- **Security**: Socket.IO rate limiting on 13 event types (per-user sliding window)
- **Security**: Message encryption at rest using Fernet (AES-128-CBC + HMAC) with key rotation via `MultiFernet`
- **Security**: 8 security response headers (CSP, HSTS, XFO, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP)
- **Security**: Server-side XSS sanitization (`sanitize_html()`) on all message/broadcast content
- **Security**: Client-side XSS prevention via `escapeHtml()` at 15+ DOM sinks
- **Security**: Session regeneration on login, register, and logout (`session.clear()`)
- **Security**: Session cookie hardening (HttpOnly, Secure, SameSite=Lax, 24h lifetime)
- **Security**: File upload validation (extension whitelist, size limits, filename sanitization, UUID rename, MIME advisory check)
- **Security**: Password validation (min 8 chars, max 128)
- **Security**: Username validation (3-50 chars, alphanumeric + `_-.@`)
- **Security**: Account enumeration mitigation (generic error messages on login/register failure)
- **Security**: Banned user detection on login and Socket.IO connect
- **Security**: Server-side sender override on all Socket.IO events (prevents spoofing)
- **Security**: Group membership verification on all group operations
- **Security**: Environment variable validation (fail-fast on missing `SECRET_KEY` and `ENCRYPTION_KEY`)
- **API**: Standardized JSON response envelope using `success_response()` / `error_response()` with `ErrorCode` enum
- **API**: 40+ standardized error codes across 8 categories (AUTH, VALIDATION, GROUP, MESSAGE, FILE, ADMIN, RATE_LIMIT, SERVER)
- **API**: Message history pagination with `limit`/`offset` (cap 200)
- **API**: Backward-compatible frontend data access (`data.data.X || data.X`)
- **Performance**: Database indexes on `message` table (`ix_message_recipient_status_sender`, `ix_message_sender_recipient_id`)
- **Performance**: Batch unread count query (single `GROUP BY` for all online users)
- **Performance**: Batch last-message retrieval (single subquery + join)
- **Architecture**: Centralized security utilities (`utils/security/`) with validators, sanitizers, decorators, permissions, constants
- **Architecture**: Centralized API helpers (`utils/api/`) with response builders and error codes
- **Architecture**: Encryption utilities (`utils/crypto/`) with Fernet key rotation
- **Documentation**: `DEPLOYMENT_GUIDE.md` with Docker, Railway, nginx, and rollback procedures
- **Documentation**: `KEY_ROTATION.md` with encryption key rotation guide
- **Documentation**: `FINAL_SECURITY_AUDIT.md` with full 16-domain security audit
- **Documentation**: `API_STANDARDIZATION_PLAN.md` documenting all 37 API endpoints
- **Testing**: 15 unit tests covering auth, history, groups, admin API, call logging

### Changed

- All 37 JSON API endpoints migrated from raw `jsonify()` to standardized `success_response()` / `error_response()` helpers
- Login/register/logout endpoints hardened with rate limiting, validation, and session regeneration
- Admin interface split into web admin (`routes/admin.py`) and optional desktop admin (`admin_app.py`)
- Database schema: added `last_seen`, `created_at`, `is_banned`, `is_admin` columns to `User`; `deleted_by_sender`, `deleted_by_recipient`, `created_at` to `Message`; `description` to `Group`

### Removed

- Hardcoded `SECRET_KEY` — now required from environment variable
- Hardcoded Fernet encryption key — now required from `ENCRYPTION_KEY` env var
- Hardcoded admin credentials — now seeded via `ADMIN_PASSWORD_HASH` env var
- Direct `jsonify()` calls in all route files

### Security (Complete Resolution)

All 12 critical/high findings from the validated security report are resolved:

| ID | Finding | Severity | Resolution |
|---|---|---|---|
| FC-001 | Hardcoded Fernet Key | CRITICAL | Moved to `ENCRYPTION_KEY` env var |
| FC-002 | Hardcoded Admin Credentials | CRITICAL | Seeded via `ADMIN_PASSWORD_HASH` env var |
| FC-003 | Hardcoded Flask Secret Key | HIGH | `SECRET_KEY` env var; app fails fast if missing |
| FC-005 | No CSRF Protection | HIGH | Flask-WTF + `csrf.js` auto-inject |
| FC-006 | Stored XSS in Chat Messages | HIGH | `escapeHtml()` at all sinks + `sanitize_html()` server-side |
| FC-007 | Stored XSS in System Broadcast | HIGH | Server-side `sanitize_html()` |
| FC-008 | Plaintext Message Storage | HIGH | Fernet encryption via `encrypt_text()` |
| FC-010 | Session Fixation | HIGH | `session.clear()` on login/register/logout |
| FC-012 | No Password Policy | HIGH | `validate_password()` min 8 chars |
| FC-013 | No Rate Limiting | HIGH | 38+ `@rate_limit()` decorators |
| FC-032 | Missing Session Timeout | MEDIUM | `PERMANENT_SESSION_LIFETIME = 24h` |

### Known Limitations

- CSP in Report-Only mode with `'unsafe-inline'` — enforcement deferred to v1.1
- No brute force account lockout — rate limiting provides partial mitigation
- In-memory rate limiter resets on restart — not suitable for multi-worker deployments
- No magic-byte file validation — extension whitelist only
- No admin audit log — structured logging deferred to v1.1
- SQLite in production — PostgreSQL deferred to v1.2

[1.0.0]: https://github.com/anomalyco/falcon-web-chat/releases/tag/v1.0.0
