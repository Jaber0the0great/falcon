# Socket.IO Security Plan

> Derived from `SOCKET_THREAT_MODEL.md`.  
> Every recommendation is ordered by severity — implement in priority order.

---

## Priority 1 — Critical (SOCK-01, SOCK-02, SOCK-03, SOCK-04, SOCK-06)

### 1.1 Validate `target` / `to` in every handler that uses it

**Affected handlers:** `send_message`, `reaction`, `delete_message`, `webrtc_signaling`

**Problem:** These handlers accept a `to` / `target` field from the client and emit to that room without verifying the sender has any relationship to it. An attacker can inject messages into private group chats, send WebRTC offers to arbitrary users, or react to messages in any room.

**Fix:**

- **`send_message`**: Before emitting, verify that `target` is one of:
  - `'All'` (always valid, global room)
  - The sender's own username (send to self)
  - A username that is NOT the sender (no additional check needed — private 1:1)
  - A group name where `GroupMember` exists for the sender
- **`reaction`**: Same `target` validation; also verify the user is a member of the group if `target` is a group name
- **`delete_message`**: Same `target` validation
- **`webrtc_signaling`**: Same `target` validation

**Implementation approach:**

Create a reusable helper in `utils/security/permissions.py`:
```python
def resolve_chat_target(target: str, username: str) -> bool:
    """Return True if *username* is allowed to send messages to *target*."""
    if target == 'All' or target == username:
        return True
    # Check if target is a user (no auth needed to DM anyone)
    if User.query.filter_by(username=target).first():
        return True
    # Check if target is a group and user is a member
    if GroupMember.query.filter_by(group_name=target, username=username).first():
        return True
    return False
```

Apply this check early in each handler before any emit/DB operation.

**Backward compatibility:** All existing valid traffic passes (DM, group chat, global). Only previously-illegal traffic (cross-room injection) is rejected.

---

### 1.2 Validate `msg_id` ownership in `message_read`

**Affected handler:** `message_read`

**Problem:** Any authenticated user can mark ANY message as read by providing its `msg_id`, even messages they are neither sender nor recipient of.

**Fix:**

Before marking as read, verify that the authenticated user is either the sender or the recipient of the message:

```python
msg = Message.query.filter_by(msg_id=msg_id).first()
if not msg:
    return
if msg.sender != username and msg.recipient != username:
    return  # Not a participant in this message
```

**Backward compatibility:** All existing valid traffic (marking own messages as read) passes. Only malicious cross-message marking is blocked.

---

### 1.3 Add `from` injection to `webrtc_signaling`

**Affected handler:** `webrtc_signaling`

**Problem:** Unlike `send_message` (which overrides `sender`) and `group_call_signaling` (which injects `from`), the 1:1 `webrtc_signaling` handler relays the entire client payload verbatim, allowing sender spoofing.

**Fix:**

```python
@socketio.on('webrtc_signaling')
def handle_webrtc(data):
    if 'user_id' not in session: return
    target = data.get('to')
    if target:
        data['from'] = session.get('username', 'unknown')
        emit('webrtc_signaling', data, room=target)
```

Also apply `resolve_chat_target()` to validate `target` (see 1.1).

**Backward compatibility:** All clients will see the `from` field overridden with the verified session username instead of any value they might have sent. This is strictly more secure and does not break any legitimate use case.

---

## Priority 2 — High (SOCK-05, SOCK-07, SOCK-08)

### 2.1 Validate and sanitize `status` in `status_update`

**Affected handler:** `status_update`

**Problem:** `data.get('status', 'Available')` stores an arbitrary string in `User.status` without length or content validation. This is rendered in the user list UI and is an XSS vector.

**Fix:**

Apply an allowlist of valid status values or sanitize the input:
- Option A (recommended): Allowlist — only accept `'Available'`, `'Busy'`, `'Away'`, `'Do Not Disturb'`, `'Offline'`, plus a limited custom text field
- Option B: Strip HTML tags and truncate to a reasonable length (e.g., 50 chars)

**Backward compatibility:** If using an allowlist, existing clients sending arbitrary custom statuses will silently fail (status stays as-is). To preserve full backward compatibility, use Option B (sanitize + truncate).

---

### 2.2 Rate limiting

**Affected handlers:** All

**Problem:** No rate limiting on any socket event. An attacker can flood:
- `send_message` → DB writes + O(n²) broadcast_user_list
- `reaction` → JSON parse + DB writes
- `status_update` → DB writes + O(n²) broadcast_user_list
- `webrtc_signaling` → relay to target (flood a specific user)

**Fix:**

Implement per-user rate limiting with configurable thresholds:

```python
from collections import defaultdict
from time import time as _time

# In-memory rate tracker (use Redis for multi-process)
_rate_limits: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

def check_rate_limit(event_key: str, max_calls: int, window_seconds: int = 1) -> bool:
    now = _time()
    user_events = _rate_limits[event_key]
    user_events[event_key] = [t for t in user_events[event_key] if now - t < window_seconds]
    if len(user_events[event_key]) >= max_calls:
        return False
    user_events[event_key].append(now)
    return True
```

Suggested limits:
| Event | Max per second | Notes |
|-------|---------------|-------|
| `send_message` | 5 | Prevents message flood |
| `reaction` | 10 | Emoji spam is low-risk but can be noisy |
| `status_update` | 2 | Status changes are infrequent |
| `webrtc_signaling` | 20 | Signaling can be bursty but should be bounded |
| `message_read` | 30 | Quick-read scenarios |

**Backward compatibility:** No impact — legitimate users stay well within these limits.

---

### 2.3 Optimize `broadcast_user_list()` or reduce call frequency

**Affected handlers:** `connect`, `disconnect`, `send_message`, `message_read`, `mark_all_read`, `status_update`

**Problem:** `broadcast_user_list()` performs an O(n²) scan of all users and all messages, called from 6 different handlers. This is a DoS amplification vector.

**Fix:**

Three approaches (implement at least the first):
1. **Debounce**: Instead of calling `broadcast_user_list()` synchronously from each handler, set a flag and debounce the actual broadcast with a short timer (e.g., 200ms). Multiple rapid triggers collapse into one broadcast.
2. **Cache**: Cache the computed user list and invalidate only when user status/read counts change, rather than recomputing from scratch.
3. **Reduce broadcast scope**: Only broadcast to affected users rather than all online users.

**Backward compatibility:** No impact — the same data is delivered, just potentially batched.

---

## Priority 3 — Medium (SOCK-09, SOCK-10, SOCK-11)

### 3.1 Enforce message content length

**Affected handler:** `send_message`

**Problem:** `MAX_MESSAGE_CONTENT_LENGTH = 10000` exists in `utils/security/constants.py` but is never used in socket handlers. Message content stored directly to DB without length validation.

**Fix:**

Before storing the message, truncate or reject based on `MAX_MESSAGE_CONTENT_LENGTH`:

```python
content = data.get('content', '')
if content and len(content) > MAX_MESSAGE_CONTENT_LENGTH:
    content = content[:MAX_MESSAGE_CONTENT_LENGTH]
```

Or reject with an error event.

**Backward compatibility:** Existing messages longer than the limit would be truncated on re-send (they were previously accepted). This only affects new messages.

---

### 3.2 Restrict CORS or document risk

**Affected:** `app.py` — `SocketIO(cors_allowed_origins="*")`

**Problem:** Any website can open a Socket.IO connection. Combined with session cookies (if the user is logged in), this creates a CSWSH (Cross-Site WebSocket Hijacking) risk: a malicious site could join rooms and receive messages.

**Fix:**

- If the app runs on a known domain, set `cors_allowed_origins` to that domain
- If multiple origins are needed, provide a list
- If wildcard is required for development, ensure:
  - Session cookies use `SameSite=Lax` or `Strict`
  - Socket.IO is served over HTTPS with `Secure` flag on cookies

**Backward compatibility:** Setting CORS to a specific origin will break connections from other origins (dev tools, browser extensions, etc.). Use a list of approved origins.

---

### 3.3 Add idempotency for `msg_id` in `send_message`

**Affected handler:** `send_message`

**Problem:** The same `msg_id` can be sent multiple times, creating duplicate messages in the DB.

**Fix:**

Before inserting, check if a message with that `msg_id` already exists:

```python
existing = Message.query.filter_by(msg_id=data.get('msg_id')).first()
if existing:
    return  # Duplicate — silently ignore
```

The `msg_id` column in the `Message` model is `unique=True, nullable=False`, so the DB constraint would catch this too (raising an IntegrityError). However, the handler currently has no try/except around the commit, so a duplicate would crash silently.

**Backward compatibility:** No impact — duplicates are already unintentional.

---

## Priority 4 — Low (SOCK-12)

### 4.1 (Optional) Add membership check to `leave_room_request`

**Affected handler:** `leave_room_request`

**Problem:** Any authenticated user can leave any room, even ones they never joined.

**Fix:** This is primarily a consistency issue. Add the same `GroupMember` check as `join_room_request`:

```python
if group_name and GroupMember.query.filter_by(group_name=group_name, username=user.username).first():
    leave_room(group_name)
```

**Backward compatibility:** No impact — a non-member leaving a room they're not in is already a no-op.

---

## Summary of Implementation Order

| Order | ID | Change | Effort | Risk if deferred |
|------|----|--------|--------|------------------|
| 1 | SOCK-01 | Validate `target` in `send_message`, `reaction`, `delete_message` | Small | Message injection into private groups |
| 2 | SOCK-02 | Validate `msg_id` ownership in `message_read` | Small | Cross-user read-status leakage |
| 3 | SOCK-03 | Inject `from` in `webrtc_signaling` | Trivial | WebRTC identity spoofing |
| 4 | SOCK-04 | Validate `target` in `webrtc_signaling` | Small | Signalling injection to arbitrary users |
| 5 | SOCK-06 | Validate target in `reaction` (same as SOCK-01) | Small | Reaction injection into groups |
| 6 | SOCK-05 | Sanitize `status` in `status_update` | Trivial | XSS via user status |
| 7 | SOCK-07 | Rate limiting | Medium | Flood-based DoS |
| 8 | SOCK-08 | Debounce/cache `broadcast_user_list()` | Medium | O(n²) DoS amplification |
| 9 | SOCK-09 | Enforce `MAX_MESSAGE_CONTENT_LENGTH` | Trivial | Oversized content in DB |
| 10 | SOCK-10 | Restrict CORS | Trivial | CSWSH risk |
| 11 | SOCK-11 | Idempotency for `msg_id` | Trivial | Duplicate messages |
| 12 | SOCK-12 | Membership check on leave | Trivial | Consistency only |

---

## Handlers NOT modified

The following handlers require no changes because they already have adequate security:

| Handler | Why adequate |
|---------|-------------|
| `connect` | Session-based auth, DB-backed authorization via GroupMember query, no user-supplied input |
| `disconnect` | Session-only, no user input |
| `mark_all_read` | Correctly scoped to `sender_username → my_username` messages |
| `delete_message` | `is_sender` check for `'everyone'` delete, `'me'` delete is self-scoped |
| `join_room_request` | `GroupMember` check before joining |
| `group_call_start` | `GroupMember` check before emitting |
| `group_call_join` | `GroupMember` check + `call_<group>` isolation |
| `group_call_signaling` | `from` injection + `GroupMember` check (in parent handler) |
| `group_call_leave` | Self-scoped, no authorization needed |
