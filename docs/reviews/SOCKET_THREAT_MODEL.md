# Socket.IO Threat Model

> Generated during Phase 4D review.  
> Covers every Socket.IO server-side event handler, room, and emit().

---

## 1. Scope

| Area | Includes |
|------|----------|
| Server handlers | `sockets/events.py` — all 15 `@socketio.on(...)` handlers |
| Internal helpers | `broadcast_user_list()` |
| REST-triggered emits | `routes/api.py` — 9 socketio.emit() calls |
| Background task | `app.py` — `background_broadcast_task()` |
| Client handlers | `static/js/socket.js` — informational only |
| **Out of scope** | WebRTC media-plane security; TLS transport |

---

## 2. Rooms

| Room | Purpose | Who joins |
|------|---------|-----------|
| `'All'` | Global broadcast | Every authenticated user on connect |
| `<username>` | Per-user private inbox | The user themselves on connect |
| `<group_name>` | Per-group chat room | Group members on connect; on `join_room_request`; via REST after accept |
| `call_<group_name>` | Per-group call signalling | Group call participants via `group_call_join` |

---

## 3. Event Inventory — Client → Server

| # | Event | Handler | Auth'd | Input Fields | DB Ops | Broadcast / Room Ops |
|---|-------|---------|--------|-------------|--------|----------------------|
| 1 | `connect` | `handle_connect` | Session `user_id`; user exists + not banned | (none — session only) | `User.status="Available"`, `last_seen`, mark undelivered `sent→delivered` | `join_room(username, 'All', group_names)`; `emit('system', ..., room='All')`; `broadcast_user_list()` |
| 2 | `disconnect` | `handle_disconnect` | Session `user_id` | (none — session only) | `User.status="Offline"`, `last_seen` | `leave_room(username, 'All')`; `emit('system', ..., room='All')`; `broadcast_user_list()` |
| 3 | `send_message` | `handle_message` | Session `user_id`; user exists | `to`, `type`, `content`, `time`, `duration`, `size`, `name`, `data`, `msg_id`, `reply_to`, `reply_content` | `Message` INSERT (non-transient types only) | `emit('new_message', ..., room=target)`; `emit('new_message', ..., room=sender)`; `emit('new_message', ..., room='All')`; ack `emit(... room=sender)`; `broadcast_user_list()` |
| 4 | `message_read` | `handle_message_read` | Session `user_id` | `msg_id` | `Message.status='read'` | `emit('message_status', ..., room=msg.sender)`; `broadcast_user_list()` |
| 5 | `mark_all_read` | `handle_mark_all_read` | Session `user_id`; user exists | `sender` | `Message.status='read'` (batch) | `emit('message_status', ...)` per message to `room=sender_username`; `broadcast_user_list()` |
| 6 | `reaction` | `handle_reaction` | Session `user_id`; user exists | `msg_id`, `emoji`, `to` | `Message.reactions` UPDATE | `emit('reaction_update', ..., room=target)` or `room=target` + `room=my_username` |
| 7 | `delete_message` | `handle_delete_message` | Session `user_id`; user exists | `msg_id`, `delete_type`, `to` | `Message` DELETE or flag update | `emit('message_deleted', ..., room=target)`; also to `username` if private |
| 8 | `webrtc_signaling` | `handle_webrtc` | Session `user_id` | `to`, plus arbitrary relayed data | (none) | `emit('webrtc_signaling', data, room=target)` |
| 9 | `status_update` | `handle_status` | Session `user_id`; user exists | `status` | `User.status` UPDATE | `broadcast_user_list()` |
| 10 | `join_room_request` | `handle_join_room_request` | Session `user_id` | `group_name` | (none) | `join_room(group_name)` — only if GroupMember exists |
| 11 | `leave_room_request` | `handle_leave_room_request` | Session `user_id` | `group_name` | (none) | `leave_room(group_name)` — **no membership check** |
| 12 | `group_call_start` | `handle_group_call_start` | Session `user_id`; user exists | `group_name` | (none) | `emit('group_call_incoming', ..., room=group_name, include_self=False)` — only if GroupMember |
| 13 | `group_call_join` | `handle_group_call_join` | Session `user_id`; user exists | `group_name` | (none) | `join_room(call_<group_name>)`; `emit('user_joined_group_call', ..., room=call_<group_name>, include_self=False)` — only if GroupMember |
| 14 | `group_call_signaling` | `handle_group_call_signaling` | Session `user_id`; user exists | `to`, plus arbitrary relayed data | (none) | Injects `data['from']`; `emit('group_call_signaling', data, room=target)` |
| 15 | `group_call_leave` | `handle_group_call_leave` | Session `user_id`; user exists | `group_name` | (none) | `leave_room(call_<group_name>)`; `emit('user_left_group_call', ..., room=call_<group_name>, include_self=False)` |

---

## 4. Threat Analysis — Per Event

### 4.1 `connect` / `disconnect`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | Low | Session is server-managed; `user_id` comes from signed cookie |
| **Replay** | Low | Socket.IO transport provides ordering; replayed `connect` just re-establishes |
| **Flood** | Medium | Rapid connect/disconnect cycles cause repeated `broadcast_user_list()` (expensive O(n²) scan) and DB writes |
| **Injection** | None | No user-supplied input |
| **Privilege escalation** | Low | Room joins are based on session user; group memberships read from DB |
| **Info disclosure** | Low | `broadcast_user_list()` sends per-user unread counts to every online user (may leak conversation partners) |

### 4.2 `send_message`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated | `data['sender']` is **overridden** with session username |
| **Replay** | Medium | No idempotency check — same `msg_id` can be sent repeatedly, creating duplicate DB rows |
| **Flood** | **High** | No rate limit; each message writes to DB and triggers `broadcast_user_list()` (O(n²)) |
| **Injection** | **High** | `content`, `file_name`, `raw_data`, `reply_content` stored directly — no length/sanitization check despite `MAX_MESSAGE_CONTENT_LENGTH` existing in constants |
| **Privilege escalation** | **Critical** | **No target validation.** `target = data.get('to', 'All')` — attacker can emit `'new_message'` to **any room** (`'All'`, any username, any group name) even if they are not a member. This lets an outsider inject messages into private group chats. |
| **Info disclosure** | Low | Messages to `'All'` are visible to everyone by design |

### 4.3 `message_read`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated | Uses session `user_id` |
| **Replay** | Medium | Repeated `msg_id` causes harmless repeated DB writes (same value) and spurious `emit()` to sender |
| **Flood** | Medium | No rate limit; each call does DB query + write + `broadcast_user_list()` |
| **Injection** | Low | `msg_id` is a string — no sanitization, but only used in a filter query |
| **Privilege escalation** | **High** | **No recipient check.** Any authenticated user can mark ANY message as `'read'` by its `msg_id`, even messages they are not sender or recipient of. |
| **Info disclosure** | Low | The `'read'` status is emitted to `msg.sender` — attacker learns the sender is online |

### 4.4 `mark_all_read`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated | Uses session `user_id` |
| **Replay** | Low | Repeated calls are idempotent (all messages already read) |
| **Flood** | Medium | Can trigger O(n) DB writes + `broadcast_user_list()` |
| **Privilege escalation** | ✅ Scoped | Only marks messages FROM `sender_username` TO authenticated user — correct scope |
| **Info disclosure** | Low | Emits status to `room=sender_username` confirming the user is online |

### 4.5 `reaction`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated | Uses `my_username` from session |
| **Replay** | Low | Repeated identical reaction is idempotent (toggle logic) |
| **Flood** | **High** | Each call does JSON parse + DB write + broadcast — no rate limit; rapid emoji toggle is cheap for attacker but expensive on server |
| **Injection** | Medium | `emoji` stored in JSON via `json.dumps()` — safe from injection but could be used to store arbitrary Unicode |
| **Privilege escalation** | **High** | **No group membership check.** `target = data.get('to', 'All')` — attacker can emit `'reaction_update'` to any room. Also can react to messages in groups they don't belong to. |

### 4.6 `delete_message`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated | Uses `username` from session |
| **Replay** | Low | Second delete on same `msg_id` is a no-op (already deleted or flagged) |
| **Flood** | Medium | Each call does DB write |
| **Privilege escalation** | ✅ Scoped | `'everyone'` delete requires `is_sender` check — correct. `'me'` delete always allowed for any participant |
| **Info disclosure** | Low | Emits `message_deleted` to room — confirms msg_id exists (valid or not) |

### 4.7 `webrtc_signaling`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | **High** | **No `from` injection.** Unlike `send_message` and `group_call_signaling`, this handler does NOT override the sender identity. The entire `data` dict (including SDP offers/answers) is relayed verbatim. An attacker can forge WebRTC offers appearing to come from other users. |
| **Flood** | **High** | No rate limit; relays arbitrary-size data to target. Can be used to flood a specific user. |
| **Injection** | Medium | Arbitrary JSON relayed; may contain SDP with embedded codecs or STUN credentials |
| **Privilege escalation** | **High** | **No target validation.** `target = data.get('to')` — attacker can send signaling to ANY user. |
| **Info disclosure** | Medium | Attacker can probe whether a username is online (if no response, the user may be offline or room doesn't exist) |

### 4.8 `status_update`

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated | Uses session `user_id` |
| **Replay** | Low | Idempotent |
| **Flood** | Medium | Each call does DB write + `broadcast_user_list()` |
| **Injection** | **High** | `data.get('status', 'Available')` — arbitrary string stored in `User.status`. No length or content validation. Could store HTML/script. Rendered in user list → **XSS vector**. |
| **Privilege escalation** | None | Only modifies own status |
| **Info disclosure** | None | Intentionally public |

### 4.9 `join_room_request`

| Threat | Risk | Description |
|--------|------|-------------|
| **Privilege escalation** | ✅ Mitigated | Checks `GroupMember` before joining — correct |
| **Flood** | Low | Room joins are cheap server-side |

### 4.10 `leave_room_request`

| Threat | Risk | Description |
|--------|------|-------------|
| **Privilege escalation** | Low | **No membership check.** Any authenticated user can leave any room. Not a security issue (leaving a room only affects the leaver) but inconsistent with `join_room_request`'s authorization. |

### 4.11 — 4.14 Group Call Events (`group_call_start`, `group_call_join`, `group_call_signaling`, `group_call_leave`)

| Threat | Risk | Description |
|--------|------|-------------|
| **Spoofing** | ✅ Mitigated (3 of 4) | `group_call_signaling` injects `data['from']`. `group_call_start` uses `user.username`. `group_call_join`/`leave` use `user.username`. |
| **Privilege escalation** | ✅ Mitigated | `start`, `join`, `signaling` all check `GroupMember` before acting. `leave` does not (not needed — leaving is self-scoped). |
| **Flood** | Medium | No rate limit on signaling relay |
| **Injection** | Medium | Signaling data is arbitrary JSON |

---

## 5. Cross-Cutting Threats

### 5.1 `broadcast_user_list()` — Performance / DoS

- Called from **6 handlers**: `connect`, `disconnect`, `send_message`, `message_read`, `mark_all_read`, `status_update`
- Iterates over ALL online users × ALL users = O(n²) DB queries + JSON serialization
- Each call emits a **personalized** payload to each online user's room
- A flood of any triggering event causes repeated O(n²) scans
- **Risk: High** — easy to amplify a small number of events into a heavy server-side workload

### 5.2 Background broadcast task (`background_broadcast_task`)

- Polls every 5 seconds for unsent `SystemBroadcast` rows
- Emits `'new_message'` to room `'All'`
- Data comes from `SystemBroadcast.message` — this is set via admin panel (should be trusted), but no output encoding is applied
- **Risk: Low** (admin-trusted input, but no XSS defense if admin account is compromised)

### 5.3 No namespace isolation

- All handlers on default namespace `/`
- If multi-tenant isolation is ever needed (e.g., separate orgs), rooms would conflict

### 5.4 CORS

- `cors_allowed_origins="*"` — any website can open a Socket.IO connection to this server
- An external attacker website could:
  1. Open a socket to the server
  2. The user must already be authenticated (Flask session cookie required)
  3. If the user visits the attacker's site while logged into the chat app, the attacker's site could make cross-origin socket connections using the user's cookies
  4. This is a **CSWSH** (Cross-Site WebSocket Hijacking) risk

### 5.5 Flask session dependency

- Socket.IO does NOT manage sessions (`manage_session=False`)
- The `session` object in `sockets/events.py` relies on Flask's session middleware
- If the session cookie is stolen (XSS, insecure transport), the attacker has full socket access
- **Risk: Medium** — session cookie lacks `SameSite=Strict` and `Secure` flags (to be verified)

---

## 6. Trust Boundary Summary

| Source | Trust Level | Rationale |
|--------|-------------|-----------|
| `session['user_id']` | **Trusted** | Set by Flask session middleware; signed cookie |
| `session['username']` | **Trusted** | Same origin — set during login |
| `data['to']` / `data.get('to')` | **Untrusted** | Client-supplied — no validation in most handlers |
| `data['msg_id']` | **Untrusted** | Client-supplied — used as query parameter |
| `data['content']`, `data['file_name']`, etc. | **Untrusted** | Client-supplied — stored directly in DB |
| `data['status']` (status_update) | **Untrusted** | Client-supplied — stored in `User.status` |
| `data['emoji']` | **Untrusted** | Client-supplied — stored in JSON |
| `data['sender']` | **Replaced** | Overridden with session username — must remain |
| `data['from']` (group_call_signaling) | **Replaced** | Injected from session — must remain |
| `SystemBroadcast.message` | **Semi-trusted** | Written by admin only, but no output encoding |
| `GroupMember` rows | **Trusted** | DB-backed — source of truth for authorization |

---

## 7. Vulnerability Register

| ID | Vulnerability | Event(s) | Severity | Status |
|----|--------------|----------|----------|--------|
| SOCK-01 | **Arbitrary-room message injection** — no target validation | `send_message`, `reaction`, `delete_message` | **Critical** | Unmitigated |
| SOCK-02 | **Arbitrary-read acknowledgment** — no recipient check | `message_read` | **High** | Unmitigated |
| SOCK-03 | **WebRTC sender spoofing** — no `from` injection | `webrtc_signaling` | **High** | Unmitigated |
| SOCK-04 | **Arbitrary-target WebRTC signaling** — no target validation | `webrtc_signaling` | **High** | Unmitigated |
| SOCK-05 | **Status field injection** — arbitrary string in `User.status` | `status_update` | **High** | Unmitigated |
| SOCK-06 | **Arbitrary-room reaction injection** — no group membership check | `reaction` | **High** | Unmitigated |
| SOCK-07 | **No rate limiting** on any event | All | **High** | Unmitigated |
| SOCK-08 | **broadcast_user_list() O(n²) DoS amplification** | All triggering events | **High** | Unmitigated |
| SOCK-09 | **Message content length not enforced** — `MAX_MESSAGE_CONTENT_LENGTH` exists but unused | `send_message` | **Medium** | Unmitigated |
| SOCK-10 | **CORS wildcard** — CSWSH risk | All | **Medium** | Unmitigated |
| SOCK-11 | **Missing idempotency** — duplicate `msg_id` allowed | `send_message` | **Medium** | Unmitigated |
| SOCK-12 | **No membership check on leave_room_request** | `leave_room_request` | **Low** | Unmitigated |

---

## 8. `emit()` Call Inventory

Every server-to-client `emit()` in the codebase:

| Location | Event | Room(s) | Payload Source |
|----------|-------|---------|----------------|
| `events.py:41` | `message_status` | `msg.sender` (the sender's room) | Server-generated (`msg_id`, `status='delivered'`) |
| `events.py:43` | `system` | `'All'` | Server-generated |
| `events.py:104` | `user_list` | `<username>` (per-user private room) | Server-generated (DB data) |
| `events.py:141` | `new_message` | `target` or `target`+`sender` or `'All'` | Mixed — `sender` overridden, rest client-supplied |
| `events.py:151` | `new_message` (ack) | `sender` | Server-generated |
| `events.py:169` | `message_status` | `msg.sender` | Server-generated (`msg_id`, `status='read'`) |
| `events.py:189` | `message_status` | `sender_username` | Server-generated |
| `events.py:247` | `reaction_update` | `target` or `target`+`my_username` | Server-generated (parsed + re-serialized JSON) |
| `events.py:275` | `message_deleted` | `target` or `target`+`username` | Mixed — `msg_id`, `to` from client |
| `events.py:283` | `message_deleted` | `username` (self only) | Server-generated |
| `events.py:293` | `webrtc_signaling` | `target` | **Fully client-controlled** (relayed verbatim) |
| `events.py:327` | `group_call_incoming` | `group_name` (excluding self) | Server-generated |
| `events.py:343` | `user_joined_group_call` | `call_<group_name>` (excluding self) | Server-generated |
| `events.py:355` | `group_call_signaling` | `target` | `data['from']` injected, rest client-supplied |
| `events.py:367` | `user_left_group_call` | `call_<group_name>` (excluding self) | Server-generated |
| `app.py:31` | `new_message` (system broadcast) | `'All'` | `SystemBroadcast.message` (admin-trusted) |
| `api.py` (9 calls) | Various | Various | Server-generated (session-based, REST-validated) |
