# Remaining Work — Falcon Web Chat

**Date:** July 3, 2026  
**Purpose:** Track all remaining engineering work by priority and category.

---

## Legend

| Icon | Meaning |
|------|---------|
| 🔴 | Critical — blocks beta/production |
| 🟠 | High — should be done before beta |
| 🟡 | Medium — recommended before production |
| ⚪ | Low — can be deferred indefinitely |

---

## 🔴 Critical — Must Fix Before Beta

### C1: Client-Side XSS in app.js

- **Category:** Security Fix
- **Files:** `static/js/app.js`, `static/js/socket.js`
- **Problem:** All user-generated message content is rendered via `innerHTML`/`insertAdjacentHTML`. No DOMPurify. Server-side `sanitize_html()` provides partial protection but could be bypassed.
- **Solution:** Integrate DOMPurify library; sanitize all user-controlled fields (`content`, `sender`, `name`, `reply_content`, `time`) before DOM insertion. Or migrate to `textContent`/`createElement`.
- **Risks:** High — message rendering will change; every message type must be visually verified
- **Tests:** Manual XSS payload testing; automated test for `<script>` stripping
- **Estimated effort:** 6-10 hours

### C2: CSRF Protection

- **Category:** Security Fix
- **Files:** `config.py`, `templates/*.html`, `static/js/app.js`, `static/js/socket.js`
- **Problem:** No CSRF tokens on any state-changing endpoint. Session-based auth over JSON API. All POST/DELETE vulnerable.
- **Solution:** Install Flask-WTF; add `{{ csrf_token() }}` to templates; include `X-CSRFToken` header in all `fetch()` calls; exempt Socket.IO.
- **Risks:** Very High — every POST/DELETE request must include CSRF token; missed tokens break features
- **Tests:** Automated: POST without token returns 400; Manual: every form/modal that triggers POST
- **Estimated effort:** 8-12 hours

### C3: HTTPS Enforcement

- **Category:** Infrastructure / Security
- **Files:** nginx configuration (new), `app.py` (bind address)
- **Problem:** App binds `0.0.0.0:5000` plain HTTP. `SESSION_COOKIE_SECURE=True` non-functional. All traffic in cleartext.
- **Solution:** Set up nginx/Caddy with Let's Encrypt TLS; reverse proxy to Flask on `127.0.0.1:5000`; add HTTP→HTTPS redirect.
- **Risks:** Medium — HTTP→HTTPS can break hardcoded API URLs
- **Tests:** SSL Labs A+ rating; WebSocket over WSS; HTTP redirects to HTTPS
- **Estimated effort:** 4-8 hours

---

## 🟠 High — Should Fix Before Beta

### H1: HTTP Rate Limiting

- **Category:** Security Fix
- **Files:** `config.py`, `routes/auth.py`, `routes/api.py`
- **Problem:** Login, register, and upload endpoints have no rate limiting. Brute-force attacks are straightforward.
- **Solution:** Install Flask-Limiter; apply limits: login 5/min, register 3/min, upload 10/min; default 200/day 50/hour.
- **Risks:** Low-Medium — legitimate users may hit limits
- **Tests:** 429 response after exceeding limit; headers present
- **Estimated effort:** 4-6 hours

### H2: Security Headers

- **Category:** Security / Infrastructure
- **Files:** Middleware (new or `app.py`)
- **Problem:** No CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy.
- **Solution:** Implement via Flask middleware or Flask-Talisman. Start CSP in report-only mode.
- **Risks:** Medium — strict CSP can break pages
- **Tests:** Verify all 11 headers via `curl -I`
- **Estimated effort:** 4-6 hours

### H3: Magic Byte File Validation

- **Category:** Security Fix
- **Files:** `routes/api.py` (upload handler)
- **Problem:** Only extension whitelist and advisory MIME check. Renamed executables bypass.
- **Solution:** Add magic byte verification using `python-magic` library.
- **Risks:** Low — may reject legitimate files with unexpected magic bytes
- **Tests:** Upload `.exe` renamed to `.jpg` → rejected
- **Estimated effort:** 4 hours

### H4: Session Invalidation on Password Reset

- **Category:** Security Fix
- **Files:** `models/models.py`, `routes/auth.py`, `routes/admin.py`
- **Problem:** Password change doesn't invalidate existing sessions. Attacker with stolen session retains access after password reset.
- **Solution:** Add `session_token` column to User model. Generate new token on password change. Validate on each request.
- **Risks:** Medium — users will be logged out on password change (desired behavior)
- **Tests:** Old session token returns 401 after password change
- **Estimated effort:** 4-8 hours

### H5: Banned User Socket Disconnect

- **Category:** Security Fix
- **Files:** `sockets/events.py`, `routes/admin.py`
- **Problem:** Ban checked on socket connect only. Active sessions continue to function after ban.
- **Solution:** Emit `force_disconnect` event in admin ban handler; client-side handler redirects to login.
- **Risks:** Low
- **Tests:** Ban active user → socket disconnect within 5 seconds
- **Estimated effort:** 2 hours

### H6: Password Complexity Policy

- **Category:** Security Fix
- **Files:** `utils/security/validators.py`, `utils/security/constants.py`
- **Problem:** Only minimum length check (6 chars). No uppercase, digit, or symbol requirement.
- **Solution:** Add requirement for at least 3 of 4 character categories (uppercase, lowercase, digits, symbols).
- **Risks:** Low — only affects new registrations
- **Tests:** Password "abc123" rejected; "Abcd1234!" accepted
- **Estimated effort:** 1-2 hours

### H7: Migration Default Password

- **Category:** Security Fix
- **Files:** `utils/migration.py`
- **Problem:** Sets password "password123" for all migrated users.
- **Solution:** Read default password from env var; log warning if env var not set.
- **Risks:** Low — migration script is development-only
- **Tests:** N/A (manual review)
- **Estimated effort:** 30 minutes

---

## 🟡 Medium — Before Production

### M1: Audit Logging

- **Category:** Security
- **Files:** `models/models.py`, `routes/admin.py`, `routes/api.py`, `sockets/events.py`
- **Problem:** No audit trail for admin actions (user create/delete/ban, message delete, broadcast, file delete).
- **Solution:** Create AuditLog model; add `log_action()` calls to all admin and sensitive user actions.
- **Risks:** Low — additive only
- **Estimated effort:** 6-8 hours

### M2: Admin Password Hash Disclosure

- **Category:** Security Fix
- **Files:** `admin_app.py:922`
- **Problem:** Desktop admin displays Werkzeug password hashes in user table.
- **Solution:** Remove the password hash column from the table display.
- **Risks:** None
- **Estimated effort:** 1 hour

### M3: TURN Credential Management

- **Category:** Security Fix
- **Files:** `routes/api.py`
- **Problem:** Default TURN credentials from public test service (`openrelay.metered.ca`).
- **Solution:** Generate short-lived TURN credentials or document production TURN configuration.
- **Risks:** Low — default credentials are for a public test service
- **Estimated effort:** 4 hours

### M4: Message Encryption at Rest

- **Category:** Security / Crypto
- **Files:** `sockets/events.py`, `utils/crypto.py`
- **Problem:** `encrypt_text()` exists but `handle_message()` saves content in plaintext. Admin viewer calls `decrypt_text()` which fails on plaintext data.
- **Solution:** Call `encrypt_text(content)` before saving text messages; ensure `decrypt_text` handles plaintext gracefully.
- **Risks:** Medium — encrypted messages cannot be rolled back
- **Estimated effort:** 4-6 hours

### M5: Background Broadcast Efficiency

- **Category:** Performance
- **Files:** `app.py`
- **Problem:** Polls `SystemBroadcast` table every 5 seconds regardless of activity.
- **Solution:** Add adaptive sleep: check every 5s for 1 minute, then back off to 30s if no broadcasts.
- **Risks:** Low
- **Estimated effort:** 2 hours

### M6: Missing Audio File Reference

- **Category:** Bug Fix
- **Files:** `templates/chat.html:744`
- **Problem:** References non-existent `/static/playing.wav`.
- **Solution:** Remove the reference or add the file.
- **Risks:** None
- **Estimated effort:** 15 minutes

### M7: Space in Filename

- **Category:** Bug Fix
- **Files:** `templates/chat.html:748`
- **Problem:** `receaved_message%20.mp3` has URL-encoded space.
- **Solution:** Rename to `receaved_message.mp3`.
- **Risks:** None
- **Estimated effort:** 15 minutes

### M8: CI/CD Pipeline

- **Category:** DevOps
- **Files:** New `.github/workflows/` directory
- **Problem:** No automated testing, security scanning, or deployment pipeline.
- **Solution:** Create GitHub Actions workflow: pytest → pip-audit → bandit.
- **Risks:** Low
- **Estimated effort:** 4-6 hours

### M9: Dependency Management

- **Category:** Supply Chain
- **Files:** `requirements.txt`
- **Problem:** Missing dependencies (Flask-Limiter, bleach, Flask-WTF, python-dotenv, gunicorn). Unused `matplotlib` in production requirements. No version pinning strategy.
- **Solution:** Audit deps; add missing; remove unused; pin major versions; organize production vs dev.
- **Risks:** Medium — version bumps may introduce breaking changes
- **Estimated effort:** 4 hours

---

## ⚪ Low — Deferred Indefinitely

### L1: Migration Script Hardcoded Paths

- **Files:** `utils/migration.py`
- **Fix:** Accept paths as CLI arguments or env vars

### L2: Background Task Re-spawn

- **Files:** `app.py`
- **Fix:** Add `except Exception` handler that logs and re-spawns the background task

### L3: Timezone Consistency

- **Files:** `sockets/events.py`, `app.py`
- **Fix:** Use `datetime.now(timezone.utc)` instead of `datetime.utcnow()`

### L4: Base64 Raw Data in Database

- **Files:** `routes/api.py`, message storage
- **Fix:** Migrate base64 file data to filesystem storage

### L5: Desktop Admin Architecture

- **Files:** `admin_app.py`
- **Fix:** Deprecate desktop admin in favor of web admin API

### L6: Formal Database Migration System

- **Files:** New `migrations/` directory
- **Fix:** Integrate Alembic for schema migrations

---

## Summary by Priority

| Priority | Count | Estimated Effort |
|----------|-------|-----------------|
| 🔴 Critical | 3 | 18-30 hours |
| 🟠 High | 7 | 20-32 hours |
| 🟡 Medium | 9 | 26-38 hours |
| ⚪ Low | 6 | 10-20 hours |
| **Total** | **25** | **74-120 hours** |

## Summary by Category

| Category | Count | Items |
|----------|-------|-------|
| Security Fix | 12 | C1, C2, H1, H3, H4, H5, H6, H7, M1, M2, M3, M4 |
| Infrastructure | 2 | C3, H2 |
| Bug Fix | 2 | M6, M7 |
| Performance | 1 | M5 |
| DevOps | 1 | M8 |
| Supply Chain | 1 | M9 |
| Architecture | 1 | L5 |
| Maintainability | 5 | L1, L2, L3, L4, L6 |
