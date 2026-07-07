# Presence System — Design Document

> Version 1.1, Phase 3  
> Status: Draft — do not implement before approval

---

## 1. Objective

Rename and redesign the current ad-hoc "Online Users" logic into a robust **Presence System** that handles multi-tab, reconnection, busy states, accurate last-seen, sorted user lists, and efficient broadcasting.

---

## 2. Current State (As-Is)

### 2.1 Data Model

| Column | Type | Default | Updated |
|---|---|---|---|
| `status` | `String(50)` | `'Available'` | On connect/disconnect/login/logout/status_update |
| `last_seen` | `DateTime` | `utcnow` | On connect and disconnect |

Valid status values: `{'Available', 'Busy', 'Offline'}` — defined in `utils/security/constants.py:176`.

### 2.2 Presence Triggers

| Trigger | Status Change | `last_seen` | Broadcast |
|---|---|---|---|
| Socket connect | `Available` | Updated | `broadcast_user_list()` |
| Socket disconnect | `Offline` | Updated | `broadcast_user_list()` |
| HTTP login | `Available` | Not updated | None |
| HTTP logout | `Offline` | Not updated | None |
| Socket `status_update` | User-chosen | Not updated | `broadcast_user_list()` |
| App startup | ALL → `Offline` | Not updated | None |

### 2.3 Broadcast Function

`sockets/events.py:106-167` — `broadcast_user_list()`:
- Queries ALL users
- Queries online users (status != `Offline`)
- For each online user, computes per-conversation unread counts and last-message time via batched GROUP BY queries
- Emits a personalized `user_list` event to EACH online user's room
- Called on: connect, disconnect, send_message, message_read, mark_all_read, status_update

### 2.4 Client-Side Sorting

Three-tier sort in `static/js/socket.js:108-129`:
1. Online status (Available users first)
2. Last message time (descending)
3. Alphabetical

### 2.5 Status UI

- Green/gray dot only (`.status-dot.online` / `.status-dot.offline`)
- "Busy" users appear the same as "Available" — no visual distinction
- No user-facing "Set Busy" button in the chat UI (admin-only)

### 2.6 Busy Handling (WebRTC)

- `webrtc.js:260-268` — rejects offers if already in a call, sends `type: 'busy'`
- `webrtc.js:307-313` — shows "X is busy in another call" when receiving busy
- This is call-busy, not status-busy

---

## 3. Identified Problems

### 3.1 No Connection Counting (Multi-Tab)

The server does not track how many Socket.IO connections a user has open. Opening tab A → status = `Available`. Opening tab B → status = `Available` (same state). Closing tab A → `handle_disconnect()` fires → status = `Offline` — even though tab B is still connected.

**Impact:** User appears offline while actively using another tab. False offline detection.

### 3.2 `broadcast_user_list()` Is Expensive

Called on every message, read, status change, connect, and disconnect. For N online users and M total users, it performs:
- 1 query for all users (M rows)
- 1 query for online users (N rows)
- 1 GROUP BY for unread counts (across all online users)
- 1 GROUP BY + subquery for last-message times
- N separate `socketio.emit()` calls

**Impact:** With 50+ online users, every message triggers 50 individual emits of the full user list. Bandwidth scales O(N*M).

### 3.3 No Status Persistence on Reconnect

App startup resets ALL users to `Offline`. A user who was `Busy` before a server restart loses that state.

### 3.4 Lost `Busy` / `In a call` Status

When a WebRTC call starts, the user's status should auto-set to `"In a call"` (or `Busy`). When the call ends, it should revert. Currently this is not implemented.

### 3.5 Binary Status Display (Green / Gray Only)

The UI only distinguishes `Available` (green dot) vs everything else (gray dot). `Busy` users get a gray dot — visually identical to `Offline`. No yellow/orange/red dot for Busy.

### 3.6 No User-Facing Status Control

Users cannot set themselves to `Busy` from the chat UI. The `status_update` socket event exists on the server but is never emitted by the frontend. Only admins can change user status.

### 3.7 `last_seen` Not Updated on Activity

`last_seen` is only updated on connect and disconnect. A user can be actively chatting for hours without `last_seen` being refreshed.

### 3.8 Race Condition on Rapid Connect/Disconnect

If a user's network flickers (disconnect followed by reconnect within seconds), the `Offline` broadcast goes out to all users followed immediately by an `Available` broadcast. This causes visual flickering and unnecessary broadcasts.

---

## 4. Proposed Architecture

### 4.1 Connection Tracking

Introduce a **connection registry** on the server:

```python
# In-memory dict: username -> set of sid
_connections: dict = {}

def on_connect(sid, username):
    _connections.setdefault(username, set()).add(sid)

def on_disconnect(sid, username):
    _connections.get(username, set()).discard(sid)
    return len(_connections.get(username, set())) == 0  # True if last connection
```

**Logic change:**
- `handle_connect`: Always add SID. Only set status → `Available` if user was `Offline`.
- `handle_disconnect`: Remove SID. Only set status → `Offline` if this was the LAST connection.

This solves multi-tab (problem 3.1) and reduces flickering (problem 3.8).

### 4.2 Heartbeat / Activity Ping

Add a lightweight heartbeat to periodically update `last_seen`:

```python
@socketio.on('heartbeat')
def handle_heartbeat():
    user = User.query.get(session['user_id'])
    if user:
        user.last_seen = datetime.utcnow()
        db.session.commit()
```

Client sends `heartbeat` every 60 seconds (configurable). No broadcast triggered.

This solves problem 3.7.

### 4.3 Debounced Broadcasts

Instead of broadcasting on every event, debounce `broadcast_user_list()`:

```python
import time

_last_broadcast = 0
_BROADCAST_DEBOUNCE_MS = 500  # 500ms

def debounced_broadcast():
    global _last_broadcast
    now = time.time() * 1000
    if now - _last_broadcast < _BROADCAST_DEBOUNCE_MS:
        return  # Skip — recent broadcast still fresh
    _last_broadcast = now
    broadcast_user_list()
```

Replace all `broadcast_user_list()` calls with `debounced_broadcast()`.

This solves problem 3.2 (partial) — reduces broadcast frequency.

### 4.4 Diff-Based User List Updates

Instead of sending the full user list to every online user on every change, compute a **diff**:

```python
def broadcast_user_diff(changed_username):
    """Send only the changed user's data."""
    user = User.query.filter_by(username=changed_username).first()
    if not user:
        return
    data = {
        "name": user.username,
        "status": user.status,
        "last_seen": user.last_seen.isoformat() + "Z" if user.last_seen else None,
    }
    socketio.emit('user_update', data, room='All')
```

Client merges `user_update` into its local `allUsersList` and re-renders. Full list only sent on initial connection.

This solves problem 3.2 (major) — reduces per-event bandwidth from O(N*M) to O(N).

### 4.5 Status Auto-Transitions

| Trigger | New Status | Notes |
|---|---|---|
| User starts a call | `Busy` | Auto-set via socket event |
| User ends a call | Previous status | Store previous status before setting `Busy` |
| User sets manually | User choice | Override auto-transitions |
| Heartbeat timeout (60s) | `Away` | NEW status — user connected but inactive |
| Heartbeat resumes | Previous | Restore on next heartbeat |

### 4.6 Status Value Expansion

```python
VALID_STATUS_VALUES = frozenset({
    'Available',    # Active, accepting messages/calls
    'Busy',         # In a call or manually set
    'Away',         # Connected but no activity for 60s
    'Offline',      # Disconnected
})
```

The admin's `'In a call'` value is dropped in favor of `'Busy'` (aligned with the server-side valid set).

### 4.7 Status Display Colors

| Status | Dot Color | Text | Notes |
|---|---|---|---|
| `Available` | Green (`#22c55e`) | "Online" | Same as current |
| `Busy` | Red/Orange (`#f97316`) | "Busy" | NEW color — distinct from green/gray |
| `Away` | Yellow (`#eab308`) | "Away" | NEW status |
| `Offline` | Gray (`#64748b`) | "Last seen: ..." | Same as current |

### 4.8 User-Facing Status Control

Add a status dropdown/selector in the chat sidebar:

```
┌──────────────────────┐
│  MyUsername       ▼  │  ← click opens status menu
│  ● Online            │
├──────────────────────┤
│  ○ Available         │  ← radio
│  ○ Busy              │  ← radio
└──────────────────────┘
```

Emits `status_update` socket event on change.

### 4.9 Reconnect Behavior

On socket reconnect:
1. Server sets status to previous value (from DB — no longer reset on reconnect)
2. Server sends full `user_list` to reconnecting user
3. Server sends `user_update` for reconnecting user to all other users

On app startup:
- **Do NOT** reset all users to `Offline`. Instead, use a heartbeat timeout: any user without a heartbeat for >120s is considered offline during broadcast.

This solves problem 3.3.

---

## 5. API Changes

### 5.1 New Socket Events

| Event | Direction | Payload |
|---|---|---|
| `heartbeat` | Client → Server | `{}` |
| `status_update` | Client → Server | `{"status": "Available"\|"Busy"}` |
| `user_update` | Server → All | `{"name", "status", "last_seen", "unread_count", "last_message_time"}` |

### 5.2 Changed Socket Events

| Event | Change |
|---|---|
| `user_list` | Only sent on initial `connect` or explicit refresh request, not on every change |
| `connect` | Only sets `Available` if current status is `Offline`; does not broadcast full list |
| `disconnect` | Only sets `Offline` if last connection; does not broadcast full list |
| `send_message` | Remove `broadcast_user_list()` — client updates `last_message_time` locally from `user_update` |

### 5.3 Removed Behavior

- App startup no longer resets all user statuses to `Offline`
- `broadcast_user_list()` no longer called from message/read handlers (replaced by `user_update` on connect/disconnect/status_change only)

---

## 6. Performance Analysis

| Scenario | Current | Proposed |
|---|---|---|
| User sends message (50 online users) | 50 emits × full list (M rows) | 1 emit × `user_update` (1 row) |
| User connects | 1 emit to self × full list | 1 emit to self × full list + 1 emit to all × `user_update` |
| 100 users, 10 msg/min each | 1000 emits/min × full list | 0 emits for messages + 2 emits/min for status changes |
| 3 concurrent tabs | 3 connects, 3 disconnects → flickering | 1 connect (first tab), 0 disconnects (other tabs don't change status) |

---

## 7. Implementation Plan

| Step | Scope | Files |
|---|---|---|
| 3a | Connection registry, multi-tab fix | `sockets/events.py`, new `utils/presence.py` |
| 3b | Heartbeat + `last_seen` refresh | `sockets/events.py`, `static/js/socket.js` |
| 3c | Debounced broadcast + diff-based updates | `sockets/events.py` |
| 3d | Status value expansion (`Away`) + colors | `utils/security/constants.py`, `static/css/style.css`, `static/js/socket.js` |
| 3e | User-facing status selector UI | `templates/chat.html`, `static/js/socket.js` |
| 3f | Auto busy on call / restore on end | `sockets/events.py`, `static/js/webrtc.js` |
| 3g | Remove startup reset + improve reconnect | `app.py`, `sockets/events.py` |
| 3h | Tests for connection registry | `tests/test_presence.py` |

---

## 8. Files Changed

| File | Change |
|---|---|
| `sockets/events.py` | Connection registry, debounced broadcast, diff-based updates, heartbeat handler, auto-busy |
| `utils/presence.py` | **NEW** — Connection registry class |
| `utils/security/constants.py` | Add `Away` to `VALID_STATUS_VALUES`, update rate limits |
| `app.py` | Remove startup status reset |
| `static/js/socket.js` | Handle `user_update`, send heartbeat, status selector UI |
| `static/js/webrtc.js` | Auto-set Busy on call start/end |
| `static/css/style.css` | Add `.busy`, `.away` status dot colors |
| `templates/chat.html` | Status selector dropdown in sidebar |
| `tests/test_presence.py` | **NEW** — Tests for connection registry and presence logic |

---

## 9. Backup Center Improvements (Deferred)

The following six improvements to the Backup & Restore Center are documented here for the **next Backup iteration** (not Phase 3):

| # | Improvement | Complexity | Notes |
|---|---|---|---|
| 1 | **Optional backup labels** | Low | Add a `label` field to the create-backup form; store in manifest as `"label": "..."`. Accept as query param in API. |
| 2 | **Optional backup notes** | Low | Add a `notes` textarea to the create form; store in manifest as `"notes": "..."`. Display in history table tooltip. |
| 3 | **Pin important backups** | Medium | Add `pinned: true` flag to backup metadata. Pinned backups excluded from pruning. Separate `pinned/` subdirectory or marker file. Pin/unpin toggle in history UI. |
| 4 | **Protect pre-import backups** | Low | Pre-import backups already have a separate retention limit (20). Add a `--protect-pre-import` flag to `prune_backups()` that skips them entirely. Verify they are excluded from manual `delete` and `prune` operations. |
| 5 | **Download manifest separately** | Low | Add `/admin/api/backup-center/manifest?filename=...` endpoint that reads and returns the `.manifest.json` sidecar or the `manifest.json` from inside a full-backup ZIP. |
| 6 | **Restore preview before confirmation** | Medium | Before restore, call `check_compatibility()` and display: schema versions, backup size, file count (for full backups), SHA256, and creation date. Show issues/warnings. User must acknowledge before proceeding. (Partially done — restore modal already shows this, but could be richer.) |

These improvements should be batched into a **Backup Center v2** iteration after Phase 3.

---

## 10. Approval Checklist

- [ ] Connection registry approach (in-memory `sid` tracking) is acceptable for single-server deployment
- [ ] Multi-tab fix: only set `Offline` on last disconnect
- [ ] Debounced broadcasts (500ms) + diff-based updates replace full-list broadcasts
- [ ] Heartbeat every 60s for `last_seen` accuracy
- [ ] New status values: `Available`, `Busy`, `Away`, `Offline`
- [ ] `Away` auto-set after 60s of no heartbeat
- [ ] Auto-busy on WebRTC call, restore on hangup
- [ ] User-facing status selector in chat sidebar
- [ ] Remove app startup status reset
- [ ] Backup Center improvements deferred to next iteration
