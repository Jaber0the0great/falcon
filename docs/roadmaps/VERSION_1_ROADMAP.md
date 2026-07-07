# Version 1.0 — Implementation Roadmap

> **Order is strict.** Complete each phase in sequence. Do not start a phase until the previous phase is fully verified.
>
> Before implementing any phase: scope, risks, migration requirements, and rollback strategy will be presented for approval.

---

## Execution Order

```
Phase A ──► Phase B ──► Phase C ──► Phase D ──► Phase E ──► Phase F
Frontend    HTTP        API         Message     Final       Release
XSS         Rate        Standard-   Encryption  Security    Review
Protection  Limiting    ization     at Rest     Audit
```

---

## Phase A — Frontend XSS Protection

### Scope
The application currently renders user-supplied content via `innerHTML` in `static/js/app.js`. The primary sink is `buildMessageHtml()`, which constructs message DOM from a template string and assigns it via `innerHTML`. Additional `insertAdjacentHTML` calls exist for reactions, emoji picker, context menus, and group management panels.

Server-side sanitization (`sanitize_html()` in `utils/security/sanitizers.py`) is the sole XSS defense. This function uses regex to strip HTML tags, then escapes via `html.escape()`. Regex-based sanitization is fragile — it can be bypassed with malformed input, Unicode variants, or nested constructs.

The CSP is in Report-Only mode, providing zero active protection against XSS.

**Work:**
1. Replace all `innerHTML` assignments with DOM creation methods (`document.createElement`, `textContent`, `setAttribute`) or use a safe interpolation library (DOMPurify).
2. Replace `insertAdjacentHTML` calls with DOM equivalents.
3. Verify all user-controlled data flows through safe sinks only:
   - Message content (text, file names, call logs)
   - Usernames in user list, group lists, message headers
   - Group names in room list
   - Reaction emoji data
   - System broadcast messages
4. Add `textContent` / `setAttribute` patterns to the build system.
5. Verify no remaining `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` usage on untrusted data.

### Risks
- **Regression risk:** DOM construction differs from innerHTML in subtle ways (whitespace, event handlers, custom elements). Every message rendering path must be visually verified.
- **Performance risk:** DOM creation is more verbose and may be slower for large message lists. Mitigated by the existing deque cache (only new messages are rendered).
- **Scope creep:** The admin dashboard (~860 lines of inline JS in `admin_dashboard.html`) also builds DOM. Its code must be audited but is lower priority (admin-only, authenticated).

### Migration Requirements
- No database changes.
- No API changes.
- Frontend-only changes. Verification requires manual testing of every message type: text, file, image, voice, call log, reply preview, system message, reaction display, context menus, group admin panels.

### Rollback Strategy
- Revert the single commit that applies Phase A changes.
- Verify the revert restores `innerHTML` behavior without errors.
- Server-side `sanitize_html()` remains active during rollback — no gap in XSS defense.

---

## Phase B — HTTP Rate Limiting

### Scope
Currently, rate limiting exists only for Socket.IO events (defined in `utils/security/constants.py` — per-event limits like `send_message: 15/s`). HTTP endpoints have NO rate limiting:
- `POST /auth/login` — unlimited, vulnerable to credential brute force
- `POST /auth/register` — unlimited, vulnerable to account creation spam
- `POST /api/upload` — unlimited, vulnerable to storage exhaustion
- All other POST/GET endpoints — unlimited

**Work:**
1. Add `Flask-Limiter` dependency (or equivalent) to `requirements.txt`.
2. Configure rate limiter with:
   - Login: 5 attempts per minute per IP (with exponential backoff or temporary lockout)
   - Register: 3 attempts per hour per IP
   - Upload: 10 per minute per user
   - General API: 60 requests per minute per user
3. Apply rate limits via decorators or Blueprint-level configuration.
4. Rate limit responses should use standard HTTP 429 status with `Retry-After` header.
5. Ensure rate limit state is configurable for multi-worker deployments (in-memory for single-process, Redis for multi-worker).

### Risks
- **False positives:** Legitimate users behind a NAT (shared IP) could be blocked if limits are too aggressive.
- **No current mechanism to whitelist:** Admin dashboard calls could trigger rate limits if admin is active. Admin routes may need higher limits.
- **In-memory state is lost on restart:** For single-process deployments, restart resets all counters. This is acceptable — attackers would also be reset.
- **Flask-Limiter with eventlet:** Must verify compatibility with the eventlet async model.

### Migration Requirements
- Add `Flask-Limiter` to `requirements.txt`.
- Add rate limit configuration to `config.py`.
- Apply decorators to route functions.
- Existing clients see new 429 responses on exceeding limits — handle gracefully in frontend JS (show user-friendly message).

### Rollback Strategy
- Remove `Flask-Limiter` import and limiter initialization from `app.py`.
- Remove rate limit decorators from route files.
- Remove `Flask-Limiter` from `requirements.txt`.
- No database impact.

---

## Phase C — API Standardization

### Scope
The application has 33+ HTTP endpoints across 4 blueprints (`auth`, `api`, `main`, `admin`). Response formats are inconsistent:

| Pattern | Example | Endpoints |
|---|---|---|
| `{"success": true, "data": ...}` | `GET /api/history` | Most API endpoints |
| `{"success": false, "error": "..."}` | `POST /auth/login` (error) | Error responses |
| `{"logged_in": true/false, "username": ...}` | `GET /auth/me` | Auth status |
| `{"success": true, "username": ..., "is_admin": ...}` | `POST /auth/login` (success) | Login success |
| HTML pages | `GET /`, `/login`, `/register` | Main routes |
| `str(e)` in 500 responses | All admin API endpoints | Internal errors |

Error field names vary: sometimes `"error"`, sometimes direct string. HTTP status codes are used but not every endpoint returns the correct code for the error type.

**Goal:** A single, predictable response envelope for all JSON endpoints.

**Work:**
1. Define the standard response envelope:
   ```json
   {
     "success": true|false,
     "data": { ... } | null,
     "error": null | {
       "code": "ERROR_CODE",
       "message": "Human-readable description"
     },
     "meta": {
       "page": 1,
       "limit": 50,
       "total": 142
     } | null
   }
   ```
2. Define a stable set of error codes (machine-readable strings):
   - `AUTH_REQUIRED`, `INVALID_CREDENTIALS`, `USER_BANNED`
   - `VALIDATION_ERROR`, `MISSING_FIELD`
   - `NOT_FOUND`, `ALREADY_EXISTS`
   - `RATE_LIMITED`, `FILE_TOO_LARGE`, `FILE_TYPE_NOT_ALLOWED`
   - `INTERNAL_ERROR`, `NOT_IMPLEMENTED`
3. Create a helper module (e.g., `utils/api_responses.py`) with:
   - `success_response(data, meta=None, status=200)`
   - `error_response(code, message, status=400)`
4. Refactor all 33+ endpoints to use the standard envelope.
5. Preserve backward compatibility:
   - Old clients that parse `{"success": true, "username": ...}` will still work — `"username"` stays inside `data`.
   - The `"error"` string field can be kept alongside the new `"error"` object for a deprecation period.
6. Standardize pagination: All list endpoints return `meta` with `page`, `limit`, `total`.
7. Admin endpoints return `str(e)` as `error.message` instead of raw leak.

### Risks
- **Backward compatibility breakage:** Frontend JS and any third-party integrations parse the current response formats. Changes must be additive or carefully migrated.
- **Scope size:** 33+ endpoints across 4 blueprints is a significant refactor. Each endpoint must be individually verified.
- **Socket.IO responses are not covered:** Socket.IO events send ad-hoc JSON packets. Standardizing those is out of scope for this phase (they are event-based, not request-response).

### Migration Requirements
- No database changes.
- Frontend JS must be audited for every API call. Calls that parse `response.username` directly (instead of `response.data.username`) must be updated.
- Socket.IO event listeners (`new_message`, `user_list`, etc.) are NOT affected.
- Admin dashboard inline JS must be updated to use new response format.

### Rollback Strategy
- Revert the commit that changes the response helpers and route handlers.
- Restore old response format.
- No database impact.
- Frontend reverts to old parsing.

---

## Phase D — Message Encryption at Rest

### Scope
Message content is currently stored in plaintext in the `message.content` column. The `utils/crypto.py` module defines `encrypt_text()` and `decrypt_text()` using Fernet symmetric encryption, but these are NOT wired into the message send/receive flow.

**What will be encrypted (ONLY):**
- `Message.content` — the text content of messages

**What will NOT be encrypted:**
- `Message.sender` — username (indexed, used for lookups)
- `Message.recipient` — target user/group (indexed, used for lookups)
- `Message.msg_type` — type discriminator
- `Message.time` — timestamp string
- `Message.msg_id` — unique identifier (UUID)
- `Message.status` — delivery status
- `Message.reactions` — JSON reaction data
- `Message.reply_to` / `Message.reply_content` — reply metadata
- `Message.file_name` / `Message.raw_data` — file metadata
- `Message.duration` — call duration
- `Message.deleted_by_sender` / `Message.deleted_by_recipient` — soft-delete flags
- `Message.created_at` — creation timestamp
- `User.password_hash` — STAYS hashed (never encrypted)
- `User.username` — STAYS plaintext
- `Group.name` — STAYS plaintext

**Work:**
1. In `sockets/events.py` `handle_message()`: Call `encrypt_text(content)` before saving to the database.
2. In `routes/api.py` `get_history()`: Call `decrypt_text(msg.content)` for each message in API responses.
3. In `routes/admin.py` `get_chat_history()`: Already calls `decrypt_text()`, verify it still works.
4. All other places that read `message.content`: Ensure they decrypt (or handle encrypted content gracefully).

### Risks
- **Key rotation is destructive:** Changing `ENCRYPTION_KEY` makes all existing encrypted messages unreadable. A key rotation strategy must be developed separately.
- **Search is impossible:** Encrypted content cannot be searched or filtered server-side. Any future search feature must search client-side (after decryption) or use a separate search index.
- **Migration of existing data:** Existing plaintext messages in the database must be migrated. See migration plan below.
- **Performance overhead:** Encryption/decryption adds latency to every message send and every history load. Fernet is fast (~1µs per message), but batch decryption for history loads may add noticeable delay for large result sets.
- **Error handling:** If decryption fails (wrong key, corrupted data), the message should return as-is or with a fallback indicator.

### Migration Plan for Existing Plaintext Messages

1. **Create a migration script** that:
   - Reads all messages where `msg_type IN ('text', 'file', 'call_log')` and `content` is not NULL and not already encrypted.
   - Encrypts each `content` field using `encrypt_text()`.
   - Updates the row in batches of 1000.
   - Logs progress and any errors.
2. **Detection of already-encrypted content:** Fernet tokens always start with `gAAAAAB` (base64-encoded). Check `content.startswith('gAAAAA')` — if it does, skip (already encrypted).
3. **Dry-run mode:** The script should support `--dry-run` to report how many messages will be affected without modifying data.
4. **Run before deployment:** Execute the migration script against the production database before deploying the new code. This way both old code (which stores plaintext) and new code (which expects encrypted) coexist safely.
5. **Verification:** After migration, verify that `decrypt_text(encrypted_content)` returns the original plaintext for a sample of messages.

### Rollback Strategy
- **Short-term (code revert):** Revert the Phase D commit. Old code does not encrypt on send and does not decrypt on read. Encrypted messages in the DB will be returned by old code as encrypted gibberish.
- **To fully recover:** Run the inverse migration script that overwrites content with the already-stored encrypted value... Wait, this is destructive. A full rollback requires:
  1. Before deploying Phase D, take a database backup.
  2. To roll back, restore the pre-Phase-D backup.
  3. Alternatively, create a decryption migration that reads, decrypts, and stores plaintext back.
- **Recommended:** Back up the database before Phase D deployment. Rollback = restore backup + revert code.

---

## Phase E — Final Security Audit

### Scope
A systematic review of the entire application after all prior phases are complete.

**Work:**
1. **Dependency audit:** Run `pip-audit` or equivalent on all dependencies in `requirements.txt`.
2. **Static analysis:** Run bandit (or equivalent SAST tool) on all Python source files.
3. **Manual code review:**
   - Verify Phase A (no innerHTML on untrusted data).
   - Verify Phase B (rate limits applied to all HTTP endpoints).
   - Verify Phase C (consistent response formats, no error leaking).
   - Verify Phase D (encryption applied, no missed plaintext paths).
4. **CSP review:**
   - Verify CSP headers are present on all routes (Phase C may have changed route structures).
   - Verify `'unsafe-inline'` is still documented as technical debt.
5. **Test suite:**
   - Run full test suite (15+ tests).
   - Verify all tests pass.
   - Add any missing tests for Phase A-D changes.
6. **Regression test:**
   - Login/register/logout flow.
   - Send/receive messages (text, file, voice, call log).
   - Group creation, invite, join request, kick, leave, delete.
   - Admin dashboard: stats, users, groups, messages, media, broadcast.
   - File upload and download.
   - WebRTC call signaling (verify signaling still works after encryption).
7. **Documentation update:**
   - Update `RELEASE_CHECKLIST.md` with any new items.
   - Update `PRODUCTION_READINESS.md` with new scores.
   - Update `DEPLOYMENT_GUIDE.md` if env vars or configs changed.

### Risks
- **Low risk:** This phase is purely analytical. No code changes are made unless critical issues are found.
- The audit may reveal issues in Phase A-D that require rework — this is expected and should be budgeted.

### Migration Requirements
- None. Pure analysis phase.

### Rollback Strategy
- No code changes = no rollback needed.
- If issues are found, each fix follows the rollback strategy of its respective phase.

---

## Phase F — Version 1.0 Release Review

### Scope
The final engineering review before tagging v1.0. This phase reproduces the analysis of `RELEASE_CHECKLIST.md` and `PRODUCTION_READINESS.md` with updated findings.

**Work:**
1. Execute the full `RELEASE_CHECKLIST.md` against the current state.
2. Update `PRODUCTION_READINESS.md` with new scores.
3. Verify all items in the checklist pass.
4. Generate the final release artifact (git tag `v1.0.0`).
5. Document any remaining known issues as "Post-v1.0" items.

### Risks
- Significant rework if Phase A-E uncovered major issues.
- Checklist may reveal items that cannot be completed without additional phases.

### Migration Requirements
- Git tag creation.
- Release notes generation.
- No database or code changes.

### Rollback Strategy
- Git tag can be deleted.
- No production impact unless deployment has already occurred.

---

## Dependency Graph

```
Phase A (Frontend XSS)
    │
    ▼
Phase B (HTTP Rate Limiting)    ← Independent of Phase A
    │
    ▼
Phase C (API Standardization)   ← Depends on Phase A (safe DOM prevents XSS via new response rendering)
    │                             Depends on Phase B (rate limit errors need standard format)
    ▼
Phase D (Encryption at Rest)    ← Depends on Phase C (API format must be stable before encrypting)
    │
    ▼
Phase E (Security Audit)        ← Depends on all prior phases
    │
    ▼
Phase F (Release Review)        ← Depends on Phase E
```

---

## Estimated Effort

| Phase | Est. Engineering Days | Risk Level |
|---|---|---|
| A — Frontend XSS Protection | 3-5 | Medium |
| B — HTTP Rate Limiting | 1-2 | Low |
| C — API Standardization | 3-5 | Medium-High |
| D — Message Encryption at Rest | 2-3 | Medium |
| E — Final Security Audit | 1-2 | Low |
| F — Release Review | 0.5 | Low |
| **Total** | **10.5-17.5** | |

---

## Phase Gating Criteria

Each phase has a gate that must be passed before the next phase begins:

| Phase | Gate |
|---|---|
| A | All `innerHTML` sinks on untrusted data eliminated. Test suite passes. |
| B | Rate limits applied to all HTTP endpoints. Login brute force protected. Test suite passes. |
| C | Every JSON endpoint returns standard envelope. Backward compatibility verified. Frontend parses new format. Test suite passes. |
| D | All new messages encrypted. Existing plaintext messages migrated. Migration script verified (dry-run + live). Read paths decrypt correctly. Test suite passes. |
| E | Full audit report generated. All critical/high findings addressed or documented as accepted risk. Test suite passes. |
| F | `RELEASE_CHECKLIST.md` 100% complete. `PRODUCTION_READINESS.md` updated. Git tag created. |
