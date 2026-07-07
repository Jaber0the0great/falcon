# User Settings — Design Document

**Version:** 1.0  
**Status:** Design — pending approval  
**Phase:** Final major user-facing feature for Version 1.1  

---

## Table of Contents

1. [UI Layout](#1-ui-layout)
2. [Section: Profile](#2-section-profile)
3. [Section: Security](#3-section-security)
4. [Section: Appearance](#4-section-appearance)
5. [Section: Presence](#5-section-presence)
6. [Section: Future Placeholders](#6-section-future-placeholders)
7. [Username Rename — Dependency Analysis](#7-username-rename--dependency-analysis)
8. [Transaction Strategy](#8-transaction-strategy)
9. [Rollback Strategy](#9-rollback-strategy)
10. [Backend Flow](#10-backend-flow)
11. [Testing Strategy](#11-testing-strategy)

---

## 1. UI Layout

### 1.1 Entry Point

A **gear icon (⚙️)** in the chat sidebar header, next to the status selector. Clicking opens a modal (not a separate page — consistent with the existing modal pattern for group creation, invites, etc.).

### 1.2 Modal Layout

```
┌──────────────────────────────────────────────────┐
│  ⚙️ User Settings                          [✕]  │  ← Header
├──────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────────────────────────┐  │
│  │ Profile   │  │                              │  │
│  │ Security  │  │   (active section content)   │  │
│  │Appearance │  │                              │  │
│  │ Presence  │  │                              │  │
│  │ Avatar    │  │                              │  │  ← Scrollable
│  │ About Me  │  │                              │  │
│  │ ...       │  │                              │  │
│  └──────────┘  └──────────────────────────────┘  │
├──────────────────────────────────────────────────┤
│  [Save Changes]  [Cancel]                        │  ← Footer
└──────────────────────────────────────────────────┘
```

- **Left sidebar:** Tab navigation (vertical list). Each tab maps to a section.
- **Right panel:** Active section content.
- Tabs use `active` class to highlight the selected section.
- Only **Save Changes** triggers backend writes. Cancel closes without side effects.

### 1.3 Tab Content

#### Profile Tab
```
┌─────────────────────────────────────┐
│ Current Username:  alice            │
│ New Username:      [____________]   │  ← with validation hint
│                                     │
│ [Check Availability]                │  ← async, calls GET /api/settings/check-username
└─────────────────────────────────────┘
```

#### Security Tab
```
┌─────────────────────────────────────┐
│ Current Password:   [____________]  │
│ New Password:       [____________]  │
│ Confirm Password:   [____________]  │
│                                     │
│ Password requirements:              │
│ • At least 6 characters             │
│ • At most 128 characters            │
└─────────────────────────────────────┘
```

#### Appearance Tab
```
┌─────────────────────────────────────┐
│ Theme:                              │
│ ○ Light   ● Dark   ○ System         │
│                                     │
│ (preview area shows sample UI)      │
└─────────────────────────────────────┘
```

#### Presence Tab
```
┌─────────────────────────────────────┐
│ Default Status:                     │
│ [Available ▼]                       │
│                                     │
│ (Only Available / Busy / Away)      │
│ Offline remains system-controlled.  │
└─────────────────────────────────────┘
```

#### Future Placeholder Tabs
```
┌─────────────────────────────────────┐
│ Avatar                              │
│ [Upload photo...]                   │
│                                     │
│ About Me                            │
│ [____________________________]      │
│                                     │
│ Notifications, Devices, Privacy     │
│ — Coming in a future version        │
└─────────────────────────────────────┘
```

---

## 2. Section: Profile

### 2.1 Change Username

**Endpoint:** `POST /api/settings/username`  
**Request:** `{ "new_username": "alice_new" }`  
**Response:** `{ "success": true, "username": "alice_new" }`

**Validation (server-side):**
1. User must be authenticated (session check).
2. `new_username` must pass `validate_username()` from `utils/security/validators.py`.
3. `new_username` must not already exist in the `User` table (case-insensitive check via `func.lower()`).
4. `new_username` must not conflict with an existing group name (since `Message.recipient` namespace is shared).
5. `new_username` must differ from current username.

**Validation (client-side, optimistic):**
1. Character set and length check before sending.
2. Async availability check via `GET /api/settings/check-username?username=alice_new`.

### 2.2 Availability Check Endpoint

**Endpoint:** `GET /api/settings/check-username?username=<value>`  
**Response:** `{ "available": true }` or `{ "available": false, "reason": "Already taken" }`  

Checks: `User` table + `Group` table (namespace collision).

---

## 3. Section: Security

### 3.1 Change Password

**Endpoint:** `POST /api/settings/password`  
**Request:** `{ "current_password": "...", "new_password": "...", "confirm_password": "..." }`  
**Validation:**
1. `current_password` must match the user's stored hash (`user.check_password()`).
2. `new_password` must pass `validate_password()`.
3. `confirm_password` must match `new_password`.
4. `new_password` must differ from `current_password`.

**Session handling after password change:**

Two strategies, ordered by preference:

| Strategy | Approach | Risk | Complexity |
|----------|----------|------|------------|
| **A — Selective invalidation** | Generate a `password_changed_at` timestamp on the `User` model. Compare against `session['password_verified_at']`. If password was changed after the session was created, force re-login. | Low — users on other devices must re-auth | Medium |
| **B — Immediate session clear** | Clear the current session and return a `requires_relogin: true` flag. The client shows a "Password changed — please log in again" message and redirects to `/login`. | Medium — user loses current chat state | Low |

**Recommendation:** Start with **Strategy B** (simpler, clearer security semantics). Strategy A can be added later.

**Flow for Strategy B:**
1. Client sends `POST /api/settings/password` with current + new password.
2. Server validates and sets the new hash.
3. Server clears the session (all tabs/devices are logged out).
4. Server returns `{ "success": true, "requires_relogin": true }`.
5. Client shows a **confirmation modal**: "Password changed successfully. You will be redirected to the login page to sign in again."
6. After a 2-second delay (or on button click), redirect to `/login`.
7. Socket.IO disconnects — the user is automatically shown as Offline.

---

## 4. Section: Appearance

### 4.1 Themes

Three options:
- **Light** — White/light gray backgrounds, dark text.
- **Dark** — Current hardcoded dark theme.
- **System** — Follows `prefers-color-scheme` media query. **Default when no explicit preference exists.**

### 4.2 Storage Strategy

| Storage | Pros | Cons | Decision |
|---------|------|------|----------|
| **Database** (new `theme` column on `User`) | Survives logout/clear-cache; consistent across devices | Adds column; requires DB migration | **Recommended** |
| **localStorage** | No server round-trip; instant | Lost on cache clear; per-device only | Not chosen — breaks cross-device |

**Decision:** Store in the `User` model with a new column.

### 4.3 Implementation

**Model change:**
```python
class User(db.Model):
    # ... existing columns ...
    theme = db.Column(db.String(20), default='system')  # 'light', 'dark', 'system'
```

**CSS approach — CSS custom properties with data attribute:**
- Add `data-theme="dark"` (or `"light"` / `"system"`) on `<html>` element.
- Define all colors as CSS custom properties in `:root[data-theme="dark"]` and `:root[data-theme="light"]`.
- For `"system"`, use a JS `matchMedia` listener to toggle between dark/light properties.
- All existing CSS that uses hardcoded colors must be refactored to use variables.

**CSS variable structure:**
```css
:root[data-theme="dark"] {
    --bg-primary: #0f172a;
    --bg-sidebar: #1e293b;
    --bg-chat: #0b1120;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --border-color: #334155;
    /* ... etc */
}

:root[data-theme="light"] {
    --bg-primary: #f8fafc;
    --bg-sidebar: #e2e8f0;
    --bg-chat: #ffffff;
    --text-primary: #0f172a;
    --text-secondary: #64748b;
    --border-color: #cbd5e1;
    /* ... etc */
}
```

**Theme application flow:**
1. On page load, the server renders `<html data-theme="{{ user.theme or 'dark' }}">`.
2. If `theme == 'system'`, override with JS `matchMedia('(prefers-color-scheme: light)')`.
3. On theme change via settings: POST to API → update DB → update `data-theme` attribute in-place (no page reload).

**Endpoint:** `POST /api/settings/theme`  
**Request:** `{ "theme": "light" | "dark" | "system" }`  
**Response:** `{ "success": true }`

---

## 5. Section: Presence

### 5.1 Default Status

- The presence section in settings lets the user choose their **default status** on login.
- Options: Available (default), Busy, Away.
- Offline is NOT an option here (system-controlled only, per Phase 3B decision).
- On login, the system sets the user's status to their saved `default_status`.
- If `default_status` is not set, defaults to `'Available'`.

**Model change:**
```python
class User(db.Model):
    # ... existing columns ...
    default_status = db.Column(db.String(20), default='Available')
```

**Endpoint:** `POST /api/settings/default-status`  
**Request:** `{ "default_status": "Available" | "Busy" | "Away" }`  
**Response:** `{ "success": true }`

**On login flow:**
In `routes/auth.py` login handler, after successful auth:
```python
user.status = user.default_status or "Available"
```

---

## 6. Section: Future Placeholders

These tabs exist in the UI but show a "Coming soon" message when clicked. No backend logic.

| Tab | Future purpose |
|-----|---------------|
| **Avatar** | Profile picture storage (file upload → `static/avatars/`) |
| **About Me** | Short bio text (max 160 chars, stored on `User.bio`) |
| **Notifications** | Per-conversation mute, push notification toggle |
| **Devices** | Active session list, remote logout |
| **Privacy** | Last seen visibility, read receipts toggle, profile visibility |

---

## 7. Username Rename — Dependency Analysis

### 7.1 Table Reference Map

| # | Table | Column(s) | Reference type | Update required? |
|---|-------|-----------|----------------|-----------------|
| 1 | `user` | `username` | **Primary identity** | Must update the row itself |
| 2 | `message` | `sender` | Who sent the message | Yes |
| 3 | `message` | `recipient` | Who received it (or group/broadcast) | Yes, but only for direct DMs |
| 4 | `message` | `reply_to` | The original sender of the replied message | Yes |
| 5 | `group` | `owner_username` | Group owner | Yes |
| 6 | `group` | `name` | **Group name** — NOT a username reference; must NOT be changed | No — this is the group's name, not a username |
| 7 | `group_member` | `username` | Member username | Yes |
| 8 | `group_member` | `group_name` | **Group name** — NOT a username | No |
| 9 | `group_invite` | `username` | Invited user | Yes |
| 10 | `group_invite` | `invited_by` | Who sent the invite | Yes |
| 11 | `group_invite` | `group_name` | **Group name** | No |
| 12 | `group_join_request` | `username` | Requester | Yes |
| 13 | `group_join_request` | `group_name` | **Group name** | No |
| 14 | `system_broadcast` | — | No username columns | No |

### 7.2 Dependency Graph

```
                    ┌─────────────┐
                    │    user     │
                    │ (username)  │  ← The single source row
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┬─────────────────┬────────────────┐
          ▼                ▼                ▼                  ▼                ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │  message   │  │   group    │  │group_member│  │   group_invite   │  │group_join_request│
   │            │  │            │  │            │  │                  │  │                  │
   │ sender ────┤  │owner_un─ ─┤  │username ───┤  │ username ────────┤  │ username ────────┤
   │ recipient─┤  └────────────┘  └────────────┘  │ invited_by ──────┤  └──────────────────┘
   │ reply_to ─┤                                   └──────────────────┘
   └────────────┘

   Total rows to touch (worst case):
     1 user row
     N message rows where sender=old_name
     M message rows where recipient=old_name
     P message rows where reply_to=old_name
     1 group row where owner_username=old_name
     Q group_member rows where username=old_name
     R group_invite rows where username=old_name
     S group_invite rows where invited_by=old_name
     T group_join_request rows where username=old_name
```

### 7.3 Reference Type Classification

| Type | Tables affected | Strategy |
|------|----------------|----------|
| **Direct identity** | `user.username` | `UPDATE` the row |
| **Foreign references** (string columns that = username) | `message.sender`, `message.recipient`, `group.owner_username`, `group_member.username`, `group_invite.username`, `group_invite.invited_by`, `group_join_request.username` | `UPDATE` with `WHERE col = old_username` |
| **Message content** (free text that may contain username) | `message.content` (encrypted) → system messages like `"🔵 alice joined the group."` | **Skip** — content is end-to-end encrypted; old username in historical messages is acceptable. |
| **System messages** generated by server | `SystemBroadcast.message` | **Skip** — these are broadcast messages containing the old name; historical accuracy is fine. |
| **Socket rooms** (runtime) | Rooms named after the username in Socket.IO | Must leave old room, join new room. |
| **Presence registry** (runtime) | `PresenceRegistry._users` keys are usernames | Must update the key. |
| **Session** (runtime) | `session['username']` | Must update. |

### 7.4 Username History Table

Every successful rename creates a history entry for audit and support.

```python
class UsernameHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # FK to User.id
    previous_username = db.Column(db.String(80), nullable=False)
    new_username = db.Column(db.String(80), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
```

A successful rename INSERTs one row. The `UsernameHistory` table is append-only (no UPDATEs, no DELETEs).

### 7.5 Username Change Cooldown

```python
# In utils/security/constants.py
USERNAME_CHANGE_COOLDOWN_DAYS: int = 30
```

No user may rename more than once within this window. The check queries `UsernameHistory`:

```python
last_change = UsernameHistory.query.filter_by(user_id=user.id).order_by(
    UsernameHistory.changed_at.desc()
).first()

if last_change:
    days_since = (datetime.utcnow() - last_change.changed_at).days
    if days_since < USERNAME_CHANGE_COOLDOWN_DAYS:
        days_remaining = USERNAME_CHANGE_COOLDOWN_DAYS - days_since
        raise ValueError(f"Must wait {days_remaining} more day(s)")
```

### 7.6 Reserved Names

The following names are reserved and cannot be used as usernames:

| Category | Reserved values |
|----------|----------------|
| System | `"System"`, `"Server"`, `"All"` |
| Admin | `"admin"`, `"administrator"`, `"root"` |
| Placeholder | `"user"`, `"guest"`, `"anonymous"`, `"deleted"` |

Stored as a `frozenset` in `constants.py`:

```python
RESERVED_USERNAMES: frozenset = frozenset({
    'System', 'Server', 'All',
    'admin', 'administrator', 'root',
    'user', 'guest', 'anonymous', 'deleted',
})
```

Validation uses case-insensitive comparison.

### 7.7 Full Validation Pipeline (Pre-Rename)

Before any UPDATE is executed, the following checks run in order:

| # | Check | Failure response |
|---|-------|------------------|
| 1 | `new_username != old_username` | "New username must be different" |
| 2 | `validate_username(new_username)` regex | "Invalid characters / length" |
| 3 | `new_username.lower() not in RESERVED_USERNAMES` | "This name is reserved" |
| 4 | `func.lower(User.username) != func.lower(new_username)` (no existing user) | "Username already taken" |
| 5 | `func.lower(Group.name) != func.lower(new_username)` (no group collision) | "Username conflicts with group name" |
| 6 | `USERNAME_CHANGE_COOLDOWN_DAYS` check | "Must wait N more day(s)" |

### 7.8 Rename Preview Endpoint

**Endpoint:** `GET /api/settings/rename-preview?new_username=alice_new`  
**Response:**
```json
{
  "success": true,
  "preview": {
    "messages_sent": 142,
    "messages_received": 89,
    "messages_replied": 12,
    "groups_owned": 2,
    "group_memberships": 5,
    "invites_sent": 3,
    "invites_received": 1,
    "join_requests": 1,
    "total_affected": 255,
    "estimated_ms": 5
  }
}
```

The preview counts rows per table (SELECT COUNT) without making any changes. The `estimated_ms` is a rough calculation based on total rows × 0.02ms per row (SQLite bulk UPDATE speed estimate).

### 7.9 SQL UPDATE Statements (ordered)

```sql
-- These are performed within a single SQLite IMMEDIATE transaction:

-- 1. Primary identity
UPDATE user SET username = :new_name WHERE username = :old_name;

-- 2. Messages sent by user
UPDATE message SET sender = :new_name WHERE sender = :old_name;

-- 3. Messages received by user (DMs only — group/broadcast recipients are NOT usernames)
UPDATE message SET recipient = :new_name WHERE recipient = :old_name;

-- 4. Reply-to references
UPDATE message SET reply_to = :new_name WHERE reply_to = :old_name;

-- 5. Group ownership
UPDATE "group" SET owner_username = :new_name WHERE owner_username = :old_name;

-- 6. Group members
UPDATE group_member SET username = :new_name WHERE username = :old_name;

-- 7. Group invites
UPDATE group_invite SET username = :new_name WHERE username = :old_name;
UPDATE group_invite SET invited_by = :new_name WHERE invited_by = :old_name;

-- 8. Join requests
UPDATE group_join_request SET username = :new_name WHERE username = :old_name;

-- 9. History log (insert)
INSERT INTO username_history (user_id, previous_username, new_username, changed_at)
VALUES (:user_id, :old_name, :new_name, :now);
```

**Total: 9 UPDATEs + 1 INSERT (10 operations).**

### 7.10 SQLite Limitation — No Transactional DDL

SQLite supports transactional DML (INSERT/UPDATE/DELETE). All operations above are DML and run inside a single `db.session` transaction. If any step fails, `db.session.rollback()` reverts ALL changes atomically.

SQLite does NOT support transactional DDL (ALTER TABLE, etc.). Since no schema changes are involved in the rename itself, this is not a concern.

---

## 8. Transaction Strategy

### 8.1 Atomic Rename Procedure

```python
from sqlalchemy import text
from datetime import datetime

def rename_user(user_id, new_username):
    """Atomically rename a user across all tables.

    Uses BEGIN IMMEDIATE to prevent SQLITE_BUSY from concurrent writers.
    If ANY step fails, ALL changes are rolled back.
    The caller is responsible for runtime state updates after commit.
    """
    user = User.query.get(user_id)
    if not user:
        raise ValueError("User not found")
    
    old_username = user.username

    # ── Pre-checks (run outside IMMEDIATE transaction) ──
    if old_username == new_username:
        raise ValueError("New username must be different")
    
    validate_username(new_username)  # raises ValidationError on failure
    
    from sqlalchemy import func
    if new_username.lower() in RESERVED_USERNAMES:
        raise ValueError("This username is reserved")
    
    existing = User.query.filter(func.lower(User.username) == func.lower(new_username)).first()
    if existing:
        raise ValueError("Username already taken")
    
    existing_group = Group.query.filter(func.lower(Group.name) == func.lower(new_username)).first()
    if existing_group:
        raise ValueError("Username conflicts with group name")
    
    # Cooldown check
    last_change = UsernameHistory.query.filter_by(user_id=user_id).order_by(
        UsernameHistory.changed_at.desc()
    ).first()
    if last_change:
        days_since = (datetime.utcnow() - last_change.changed_at).days
        if days_since < USERNAME_CHANGE_COOLDOWN_DAYS:
            remaining = USERNAME_CHANGE_COOLDOWN_DAYS - days_since
            raise ValueError(f"Must wait {remaining} more day(s)")
    
    # ── Begin IMMEDIATE transaction ──
    # Acquires write lock upfront to avoid SQLITE_BUSY deadlocks
    db.session.execute(text("BEGIN IMMEDIATE"))
    
    try:
        user.username = new_username
        
        from sqlalchemy import update as sa_update
        
        # Message sender
        db.session.execute(
            sa_update(Message).where(Message.sender == old_username)
            .values(sender=new_username)
        )
        
        # Message recipient (DMs only — group/broadcast names stay unchanged)
        db.session.execute(
            sa_update(Message).where(Message.recipient == old_username)
            .values(recipient=new_username)
        )
        
        # Message reply_to
        db.session.execute(
            sa_update(Message).where(Message.reply_to == old_username)
            .values(reply_to=new_username)
        )
        
        # Group owner
        db.session.execute(
            sa_update(Group).where(Group.owner_username == old_username)
            .values(owner_username=new_username)
        )
        
        # Group member
        db.session.execute(
            sa_update(GroupMember).where(GroupMember.username == old_username)
            .values(username=new_username)
        )
        
        # Group invite
        db.session.execute(
            sa_update(GroupInvite).where(GroupInvite.username == old_username)
            .values(username=new_username)
        )
        db.session.execute(
            sa_update(GroupInvite).where(GroupInvite.invited_by == old_username)
            .values(invited_by=new_username)
        )
        
        # Group join request
        db.session.execute(
            sa_update(GroupJoinRequest).where(GroupJoinRequest.username == old_username)
            .values(username=new_username)
        )
        
        # History log
        db.session.add(UsernameHistory(
            user_id=user_id,
            previous_username=old_username,
            new_username=new_username,
            changed_at=datetime.utcnow()
        ))
        
        # ── Commit all or rollback all ──
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    
    # ── Post-commit: update runtime state ──
    # (see section 8.3)
```

### 8.2 Runtime State Updates (Post-Commit)

After the DB transaction commits, the following runtime state must be updated:

| Component | Action | Failure consequence |
|-----------|--------|-------------------|
| `session['username']` | Set to `new_username` | Client sees old name until next page load |
| `session['user_id']` | Unchanged (ID is immutable) | None |
| Presence registry | Remove old key, add new key with same state | Other users see old name in presence until next user_update |
| Socket.IO rooms | Leave old-username room, join new-username room | DMs routed to old room until reconnect |
| Socket.IO `register` event | Notify server of new username | Presence registry updated on next heartbeat |

**Since these are runtime-only, they cannot break the transaction.** If the commit succeeds, the DB is consistent. Runtime state can lag temporarily without causing data corruption.

**Recommended runtime update pattern:**

```python
# After successful commit:
old_name = session['username']
session['username'] = new_username

# Update presence registry
registry.rename_user(old_name, new_username)

# Update Socket.IO room membership
leave_room(old_name)
join_room(new_username)

# Notify all connected clients
emit('user_rename', {
    'old_username': old_name,
    'new_username': new_username,
}, room='All')

# Broadcast updated user list
broadcast_user_list()
```

### 8.3 User Rename Socket Event

**Purpose:** Notify all connected clients that a user changed their name, so the UI can update in-place without a full user_list reload.

**Event:** `user_rename`  
**Payload:** `{ "old_username": "alice", "new_username": "alice_new" }`  
**Client handler:** Update `window.allUsersList` entries, update `currentTarget` if viewing this user, update all group membership displays, update message history sender/recipient displays.

---

## 9. Rollback Strategy

### 9.1 Database Rollback

If the commit fails:
- `db.session.rollback()` reverts ALL 9 UPDATE statements.
- The `User.username` stays at `old_username`.
- No data loss occurs.
- The API returns an error to the client.
- The client shows a failure toast.

### 9.2 Runtime Rollback (Post-Commit Failure)

If the DB commit succeeds but a runtime update fails:
- **The DB is correct** — no runtime rollback needed.
- The user can refresh the page to pick up the correct runtime state.
- Socket.IO will sync the new username on the next `user_list` broadcast.
- **No data corruption** — only transient display issues.

### 9.3 Client-Side Rollback

If the API returns an error:
- The client restores the old username in the input field.
- A toast shows "Failed to rename: <reason>".
- The settings modal stays open for correction.

### 9.4 Safety Net — Admin Recovery

The admin dashboard already has user management. If a rename goes wrong:
1. Admin can see the user's new (or old) username in the user list.
2. Admin can manually rename via the admin API.
3. The admin `User.query` access provides full visibility into the rename state.

---

## 10. Backend Flow

### 10.1 Route Structure

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| `GET` | `/settings` | Render settings page | Session |
| `GET` | `/api/settings/rename-preview` | Preview rename impact (counts) | Session |
| `GET` | `/api/settings/check-username` | Availability check | Session |
| `POST` | `/api/settings/username` | Change username (atomic, cooldown-checked) | Session |
| `POST` | `/api/settings/password` | Change password | Session |
| `POST` | `/api/settings/theme` | Change theme | Session |
| `POST` | `/api/settings/default-status` | Change default presence | Session |
| `GET` | `/api/settings` | Get current settings | Session |

### 10.2 Blueprint: `routes/settings.py`

New file. Registered as `settings_bp` in `app.py`.

### 10.3 Template: `templates/settings.html` or Modal in `chat.html`

**Option A — Separate page** (`/settings`):
- Clean URL, easy to bookmark.
- Must add a new route, template, and navigation link.
- User leaves the chat context.

**Option B — Modal in `chat.html`**:
- No page navigation — user stays in chat.
- Consistent with group creation, invite, forward modals.
- All logic in existing CSS/JS scope.

**Decision: Option B (Modal).** Line with existing UX patterns.

### 10.4 Settings Data Model

No separate `Settings` table. All settings are stored as columns on the `User` model:

```python
class User(db.Model):
    # Existing columns:
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    status = db.Column(db.String(50), default='Available')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # New columns:
    theme = db.Column(db.String(20), default='system')       # 'light', 'dark', 'system'
    default_status = db.Column(db.String(20), default='Available')  # 'Available', 'Busy', 'Away'
```

**Rationale for storing on `User`:**
- 1:1 relationship — each user has exactly one set of settings.
- No separate table means no join queries.
- Simpler transaction management during rename.
- No orphaned settings rows.

### 10.5 Settings API Response

```json
GET /api/settings
{
  "success": true,
  "data": {
    "username": "alice",
    "theme": "dark",
    "default_status": "Available"
  }
}
```

This is used to populate the settings modal on open and is separate from the per-tab save endpoints.

---

## 11. Testing Strategy

### 11.1 Unit Tests

| Test | Scope | What to verify |
|------|-------|----------------|
| `test_rename_user_success` | `rename_user()` function | All 9 UPDATEs execute, commit succeeds, `old_username` becomes `new_username` |
| `test_rename_user_taken` | `rename_user()` function | Raises error if new name exists |
| `test_rename_user_same` | `rename_user()` function | Raises error if new == old |
| `test_rename_user_group_conflict` | `rename_user()` function | Raises error if conflicts with group name |
| `test_rename_user_rollback` | `rename_user()` function | Inject failure after partial updates; verify all rows unchanged |
| `test_change_password` | Route | Current password correct → hash updated |
| `test_change_password_wrong_current` | Route | Current password wrong → rejected |
| `test_change_password_invalid_new` | Route | Too short / too long → rejected |
| `test_change_password_session_cleared` | Route | After success, session is cleared |
| `test_set_theme` | Route | `theme` column updated correctly |
| `test_set_theme_invalid` | Route | Invalid value → rejected |
| `test_set_default_status` | Route | `default_status` column updated |
| `test_set_default_status_offline_rejected` | Route | 'Offline' → rejected |
| `test_login_uses_default_status` | Auth flow | After login, `user.status == user.default_status` |

### 11.2 Integration Tests

| Test | What to verify |
|------|----------------|
| `test_full_rename_lifecycle` | Login → rename → verify session updated → verify messages show new name → verify groups show new name → verify presence shows new name → verify can login with new name |
| `test_rename_disconnect_socket` | During rename, socket disconnect emits correct `user_rename` event to all rooms |
| `test_password_change_forces_relogin` | After password change, accessing `/` redirects to `/login` |
| `test_theme_persists_across_sessions` | Set theme → logout → login → verify `data-theme` matches |
| `test_default_status_on_reconnect` | Set default_status='Busy' → disconnect → reconnect → verify status is Busy |

### 11.3 Frontend Tests

| Test | What to verify |
|------|----------------|
| Settings modal opens/closes | Click gear → modal visible; click ✕ → modal hidden |
| Username availability | Type name → async check → ✓ or ✗ indicator |
| Password confirm match | Type different passwords → visual error; type matching → clear |
| Theme selector | Click Light → CSS variables switch; click Dark → revert |
| Theme persistence | Reload page → theme from API/DB is applied |
| `user_rename` event handling | Receive event → update all references in user list, groups, messages |
| Validation display | Empty fields → error shown; invalid input → error shown |

### 11.4 Edge Cases

| Case | Expected behavior |
|------|------------------|
| Rename to name with different case | `"Alice"` → `"alice"` — allowed if `func.lower` check passes (no other user with that case variant) |
| Rename during active call | Call is tied to socket SIDs, not usernames — call continues uninterrupted |
| Rename in a group of 10k members | Single `UPDATE group_member SET username=... WHERE username=...` — one query regardless of group count |
| Rename while user has 50k messages | Single `UPDATE message SET sender=... WHERE sender=...` — one query regardless of message count |
| Password change during active session on another device | Strategy B: other device's next request fails auth → redirect to login |
| Theme set to `system` on a device without `matchMedia` | Falls back to dark theme (current default) |

---

## Appendix A: Summary of Changes by File

| File | Change type | Description |
|------|-------------|-------------|
| `models/models.py` | Edit | Add `theme`, `default_status` columns to `User` |
| `routes/settings.py` | **New** | Settings blueprint with 7 endpoints |
| `app.py` | Edit | Register `settings_bp` blueprint |
| `templates/chat.html` | Edit | Add settings modal HTML, CSS variables for theme support |
| `static/css/style.css` | Edit | Refactor hardcoded colors → CSS custom properties; add `[data-theme]` light/dark variants |
| `static/js/socket.js` | Edit | Add `user_rename` event handler, `window.updateUsernameRefs()` |
| `static/js/settings.js` | **New** | Settings modal logic, form handling, theme toggle, username availability check |
| `routes/auth.py` | Edit | Login handler sets `user.status = user.default_status` |
| `utils/presence.py` | Edit | Add `rename_user(old, new)` method to `PresenceRegistry` |
| `sockets/events.py` | Edit | Add `user_rename` socket event broadcast on username change |
| `tests/test_settings.py` | **New** | Unit + integration tests for all settings endpoints |
| `tests/test_presence.py` | Edit | Add tests for `registry.rename_user()` |
