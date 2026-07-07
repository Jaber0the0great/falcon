# Phase A — Frontend XSS Sink Analysis

> Complete audit of every DOM insertion point for user-controlled content.
> Read before any code changes.

---

## 1. Classification Legend

**Data Trust Levels:**
- **Trusted** — server-originated, validated, non-user-controlled (e.g., static config, server-generated IDs)
- **Untrusted** — originates from or passes through user input (even if server-validated)
- **Unsafe** — untrusted data inserted via raw HTML method without sanitization

**Insertion Methods:**
- `innerHTML` / `outerHTML` — **UNSAFE** with untrusted data
- `insertAdjacentHTML` — **UNSAFE** with untrusted data
- `innerText` / `textContent` — **SAFE** with any data (browser-safe)
- `createElement` + `appendChild` — **SAFE** if `textContent` used for user data
- `document.write` — not used anywhere

---

## 2. Complete Sink Inventory

### 2.1 `static/js/app.js`

#### Sink A1 — `loadHistory()` → `mc.innerHTML` (line 227)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | Concatenation of `buildMessageHtml(packet)` for all messages |
| **Untrusted data in path** | `packet.content` (message text), `packet.sender` (username), `packet.name` (filename), `packet.status`, `packet.reactions` |
| **Server-side protection** | `packet.content` passes through `sanitize_html()` in `sockets/events.py` before storage. `packet.sender` is forced to authenticated user server-side. Filenames are sanitized via `sanitize_filename()`. |
| **Classification** | **UNSAFE** — relies entirely on server-side sanitization. `sanitize_html()` is regex-based (`HTML_TAG_PATTERN = r'<[^>]*>'`) which is fragile. |
| **Fix required** | **YES** — replace entire path with DOM-based rendering |

#### Sink A2 — `appendMessage()` → `insertAdjacentHTML('beforeend', ...)` (line 241)

| Field | Value |
|---|---|
| **Method** | `insertAdjacentHTML` |
| **Data** | `buildMessageHtml(packet)` — same as A1 |
| **Classification** | **UNSAFE** — identical data path to A1 |
| **Fix required** | **YES** — same as A1 |

#### Sink A3 — `buildMessageHtml(packet)` (lines 12-210)

This function constructs an HTML string via template literals. It is the **central rendering function** for ALL chat messages. Every message type (text, file, call_log) and every UI element (reply bubbles, status, reactions, context menus) is built here.

**Data flows through this function:**

| Variable | Source | Server-side sanitized? | HTML-safe? |
|---|---|---|---|
| `packet.content` | User message text | YES — `sanitize_html()` at send time | Depends on regex quality |
| `packet.sender` | Server from session | YES — server-forced | Username validated to `^[a-zA-Z0-9_\-\.@]+$` |
| `packet.name` | Uploaded filename | YES — `sanitize_filename()` | Extension whitelist + UUID prefix |
| `packet.reply_content` | Copied from original message content | YES — though `reply_content` is set client-side before send | Client-side constructed, but server stores sanitized |
| `packet.reactions` | JSON string of emoji -> usernames | NO — stored as-is from server, but emoji are set by clicking predefined buttons | Usernames validated; emoji are predefined Unicode |
| `packet.status` | Server | Server-generated | Trusted |

**Sub-sinks within `buildMessageHtml`:**

| Sub-sink | Line(s) | Data | Classification |
|---|---|---|---|
| `contentHtml` (text type) | 29 | `packet.content` | **UNSAFE** — raw HTML from user text |
| `contentHtml` (file/image) | 35-46 | `packet.name`, `packet.data` (base64) | **CONDITIONALLY SAFE** — filenames are sanitized, base64 data is self-contained |
| `contentHtml` (file/audio) | 48-54 | `packet.name` | **CONDITIONALLY SAFE** |
| `contentHtml` (file/other) | 57-74 | `packet.name`, `formatSize(packet.size)` | **CONDITIONALLY SAFE** — `formatSize` returns numeric string |
| `contentHtml` (call_log) | 114-120 | `packet.content` (call status string) | **CONDITIONALLY SAFE** — status is `'completed'`, `'busy'`, `'rejected'`, or duration number |
| `replyBubbleHtml` | 25 | `_rSender`, `_rText` (from `packet.reply_content`) | **UNSAFE** — reply_content is user-text-derived |
| `statusHtml` | 127 | `packet.status`, `packet.msg_id` | **SAFE** — status is server-enumerated (`sent`/`delivered`/`read`) |
| `reactionsInnerHtml` | 140-142 | Emoji + usernames from `packet.reactions` | **LOW RISK** — emoji are predefined (👍❤️😂etc), usernames are validated. `_safeToStr` strips single quotes. |
| `dropdownItemsHtml` | 148-201 | `packet.msg_id`, `packet.sender`, `packet.type`, `packet.to`, `packet.name` | **SAFE** — msg_id is UUID, sender is validated, to is validated, name is sanitized. Submenu emoji list is hardcoded. |

#### Sink A4 — `showToast(message)` → `insertAdjacentHTML` (line 864)

| Field | Value |
|---|---|
| **Method** | `insertAdjacentHTML('beforeend', ...)` |
| **Data** | `message` parameter embedded in template literal |
| **Untrusted callers** | `copyMessageText` → static "Copied to clipboard!" (safe) |
| | `forwardMessagesToTarget` → static "Messages forwarded!" (safe) |
| | Group operations → static strings like "Group created!" (safe) |
| | `socket.js:343` — `showToast(text)` where `text` = `data.content` from server's `system` event (server-controlled) |
| | `socket.js:548` — `showToast(\`...${data.group_name}...\`)` where `group_name` is server-controlled |
| | `socket.js:596` — `showToast(\`...${data.username}...\`)` where `username` is server-controlled |
| **Risk** | The toast template literal contains `message` in: `<i class="bi bi-info-circle me-2"></i> ${message}` — this is in innerHTML context. If any caller passes unsanitized user text, XSS is possible. |
| **Classification** | **UNSAFE** — message is interpolated into innerHTML without sanitization. Currently only called with server-controlled or static strings, but the function signature accepts arbitrary text. |
| **Fix required** | **YES** — use `textContent` for the message span |

#### Sink A5 — `applyReactions()` → `container.innerHTML` (line 946)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | Emoji + usernames from `packet.reactions` JSON |
| **Classification** | **LOW RISK** — usernames are validated alphanumeric, emoji are from predefined click handlers. The only HTML-unsafe character in usernames is `.` which has no XSS significance. |
| **Fix required** | **YES** — use DOM creation to be safe |

#### Sink A6 — `populateForwardTargets()` → `item.innerHTML` (lines 836, 985)

| Field | Value |
|---|---|
| **Method** | `innerHTML` on `createElement('button')` and `createElement('div')` |
| **Data** | `u.name` (username) |
| **Classification** | **LOW RISK** — usernames validated to alphanumeric + `_-.@` |
| **Fix required** | **YES** — use `textContent` for username spans |

#### Sink A7 — Group admin panels (lines 1230, 1264-1266)

| Field | Value |
|---|---|
| **Method** | `item.innerHTML` on `createElement('div')` |
| **Data** | Usernames from API responses |
| **Classification** | **LOW RISK** — usernames validated server-side |
| **Fix required** | **YES** — use `textContent` for username spans |

---

### 2.2 `static/js/socket.js`

#### Sink B1 — `user_list` handler: `chatBtn.innerHTML` (line 165)

| Field | Value |
|---|---|
| **Method** | `innerHTML` on `createElement('button')` |
| **Data** | `u.name` (username), `u.status` (enum), `formatLastSeenRelative(u.last_seen)` (time string), `u.unread_count` (number) |
| **Classification** | **LOW RISK** — usernames validated, status is enum, last_seen is ISO date string, unread_count is number |
| **Fix required** | **YES** — use DOM creation with `textContent` for username |

#### Sink B2 — `renderRoomsList()`: `rl.innerHTML = html` (line 426)

| Field | Value |
|---|---|
| **Method** | `innerHTML` on the rooms list container |
| **Data** | `g.name` (group name), static strings for Broadcast Room |
| **Classification** | **LOW RISK** — group names validated to `^[a-zA-Z0-9_\-\s]+$` |
| **Fix required** | **YES** — use DOM creation for group name rendering. The inline `onclick` handlers with string-interpolated group names are also a vector if group name contains special characters. |

#### Sink B3 — `group_invite_received`: `modalTextEl.innerHTML` (line 560)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | `data.invited_by` (username), `data.group_name` (group name) |
| **Classification** | **LOW RISK** — both validated server-side |
| **Fix required** | **YES** — use `textContent` for the interpolated variables |

#### Sink B4 — `selectGroup()` non-member screen: `actionsContainer.innerHTML` (lines 494-508)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | `groupName` (group name) |
| **Classification** | **LOW RISK** — group name validated |
| **Fix required** | **YES** — use DOM creation |

---

### 2.3 `templates/admin/admin_dashboard.html`

**Note:** Admin-only page. Lower risk but should still be fixed.

#### Sink C1 — Toast: `toast.innerHTML` (~line 655)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | `message` parameter |
| **Classification** | **UNSAFE** — same pattern as app.js `showToast` |
| **Fix required** | **YES** — use textContent for message |

#### Sink C2 — User table: `tr.innerHTML` (~line 822)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | `u.username`, `u.status`, `u.is_banned`, `u.created_at`, `u.last_seen` |
| **Classification** | **LOW RISK** — usernames validated |
| **Fix required** | **YES** — use DOM creation |

#### Sink C3 — Chat viewer: `container.innerHTML` (lines 1106-1181)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | Decrypted message content from admin API |
| **Classification** | **UNSAFE** — message content was decrypted server-side and could contain raw HTML if `sanitize_html()` was bypassed at send time |
| **Fix required** | **YES** — use DOM creation with `textContent` for message body |

#### Sink C4 — Group members: `tr.innerHTML` (~lines 1288, 1414)

| Field | Value |
|---|---|
| **Method** | `innerHTML` |
| **Data** | Usernames, group names |
| **Classification** | **LOW RISK** — validated |
| **Fix required** | **YES** — use DOM creation |

---

### 2.4 `templates/login.html`

#### Sink D1 — `alert(data.error)` (line 41)

| Field | Value |
|---|---|
| **Method** | `alert()` — NOT a DOM injection sink |
| **Classification** | **SAFE** — `alert()` renders plain text, not HTML |

### 2.5 `templates/register.html`

#### Sink E1 — `alert(data.error)` (line 37)

| Field | Value |
|---|---|
| **Method** | `alert()` |
| **Classification** | **SAFE** |

### 2.6 `static/js/webrtc.js`

#### Sink F1 — `ensureDOMExists()`: `createContextualFragment(screenHtml)` (line 93)

| Field | Value |
|---|---|
| **Method** | `Range.createContextualFragment()` |
| **Data** | Static template string — NO user data |
| **Classification** | **SAFE** — all content is hardcoded UI |

#### Sink F2 — `ensureDOMExists()`: `insertAdjacentHTML('beforeend', audioHtml)` (line 100)

| Field | Value |
|---|---|
| **Method** | `insertAdjacentHTML` |
| **Data** | Static template string — NO user data |
| **Classification** | **SAFE** |

#### Sink F3 — `startCall`, `showCallingUI`, `showRingingUI`, etc.

| Field | Value |
|---|---|
| **Method** | `innerText` |
| **Data** | `target` (username from `selectUser`/call invitation), `caller` |
| **Classification** | **SAFE** — `innerText` is safe |

---

## 3. Summary Table

| # | File | Line(s) | Method | Data | Risk | Fix |
|---|---|---|---|---|---|---|
| A1 | app.js | 227 | `innerHTML` | All message HTML | **HIGH** | Replace with DOM rendering |
| A2 | app.js | 241 | `insertAdjacentHTML` | All message HTML | **HIGH** | Replace with DOM rendering |
| A3 | app.js | 12-210 | Template literal | Message content, sender, filename | **HIGH** | Split into DOM functions with `textContent` |
| A4 | app.js | 864 | `insertAdjacentHTML` | Toast message text | **MEDIUM** | Use `textContent` for message span |
| A5 | app.js | 946 | `innerHTML` | Reaction emoji + usernames | **LOW** | Use DOM creation |
| A6 | app.js | 836,985 | `innerHTML` | Usernames in modals | **LOW** | Use `textContent` |
| A7 | app.js | 1230,1264 | `innerHTML` | Usernames in admin panels | **LOW** | Use `textContent` |
| B1 | socket.js | 165 | `innerHTML` | Usernames in user list | **LOW** | Use DOM creation |
| B2 | socket.js | 426 | `innerHTML` | Group names in rooms list | **LOW** | Use DOM creation |
| B3 | socket.js | 560 | `innerHTML` | Invite sender + group name | **LOW** | Use `textContent` |
| B4 | socket.js | 494-508 | `innerHTML` | Group name in non-member screen | **LOW** | Use DOM creation |
| C1 | admin_dashboard.html | ~655 | `innerHTML` | Toast message text | **MEDIUM** | Use `textContent` |
| C2 | admin_dashboard.html | ~822 | `innerHTML` | Usernames in user table | **LOW** | Use DOM creation |
| C3 | admin_dashboard.html | ~1156 | `innerHTML` | Decrypted message content | **HIGH** | Use `textContent` |
| C4 | admin_dashboard.html | ~1288 | `innerHTML` | Usernames + group names | **LOW** | Use DOM creation |
| D1 | login.html | 41 | `alert()` | API error message | **SAFE** | None needed |
| E1 | register.html | 37 | `alert()` | API error message | **SAFE** | None needed |
| F1 | webrtc.js | 93 | `createContextualFragment` | Static UI only | **SAFE** | None needed |
| F2 | webrtc.js | 100 | `insertAdjacentHTML` | Static UI only | **SAFE** | None needed |
| F3 | webrtc.js | 133,158,178 | `innerText` | Usernames, static strings | **SAFE** | None needed |

---

## 4. DOMPurify Requirements Assessment

**DOMPurify is required when HTML rendering is a real requirement and the data is untrusted.**

| Scenario | Requires DOMPurify? | Rationale |
|---|---|---|
| Message text content | **NO** | `textContent` is sufficient — plain text messages should NOT render HTML |
| File name display | **NO** | `textContent` is sufficient |
| Username display | **NO** | `textContent` is sufficient, usernames are plain text |
| Group name display | **NO** | `textContent` is sufficient |
| Call log text display | **NO** | `textContent` is sufficient |
| Emoji reaction display | **NO** | `textContent` is sufficient |
| Timestamps | **NO** | `textContent` is sufficient |
| Reply preview | **NO** | `textContent` is sufficient |
| Admin chat viewer | **NO** | `textContent` is sufficient for message body |

**Conclusion: DOMPurify is NOT required for any sink.** Every case can use `textContent` or DOM creation methods (`document.createElement`, `appendChild`, `setAttribute`). The current application does not have any legitimate requirement to render user-supplied HTML.

---

## 5. Attack Surface Analysis

### Most Critical Path

```
User types message → Socket.IO send_message → Server sanitize_html() → 
DB store → GET /api/history → Response JSON → buildMessageHtml() → innerHTML
```

**Bypass scenarios for `sanitize_html()`:**

1. **Unicode normalization bypass** — `sanitize_html()` uses `re.compile(r'<[^>]*>')`. If a browser interprets Unicode variants of `<` or `>` (e.g., fullwidth characters `＜` `＞`), the regex won't match but the browser might interpret them. However, modern browsers do NOT render fullwidth angle brackets as HTML.
   
2. **Nested tag bypass** — The regex `<[^>]*>` matches anything between angle brackets. Nested tags like `<a<b>>` would match `<a<b>>` as a single tag. The inner tag wouldn't be stripped. This is a known regex limitation.

3. **Event handler bypass without tags** — Not possible without `<` and `>`.

4. **Null byte injection** — `sanitize_filename()` handles null bytes via `DANGEROUS_FILENAME_CHARS`, but `sanitize_html()` does not. A null byte before `<` might bypass the regex if the browser strips it.

### Secondary Paths

- **Username in user list** — Low risk due to validation regex `^[a-zA-Z0-9_\-\.@]+$`
- **Group name in rooms list** — Low risk due to validation regex `^[a-zA-Z0-9_\-\s]+$`
- **Toast messages** — Currently only called with controlled/static strings, but the function itself is a sink
- **Admin dashboard** — Admin-only, but admin accounts are high-value targets

---

## 6. Recommended Fix Strategy

### Tier 1 (Critical — Fix First)
1. Replace `buildMessageHtml()` with DOM-based rendering (createElement + textContent)
2. Replace `loadHistory()` and `appendMessage()` to use DOM methods instead of innerHTML/insertAdjacentHTML
3. Fix admin dashboard chat viewer message rendering

### Tier 2 (Medium Priority)
4. Fix `showToast()` to use textContent for the message body
5. Fix `applyReactions()` to use DOM creation
6. Fix `user_list` handler chatBtn construction

### Tier 3 (Low Priority)
7. Fix `renderRoomsList()` group list rendering
8. Fix group invite modal innerHTML
9. Fix admin dashboard tables (user table, group table, media table)

---

## 7. Sinks That Will Use `textContent`

After Phase A, these sinks will use `textContent` for user data:

| Sink | What changes |
|---|---|
| Message body (text type) | `<span>.textContent = packet.content` |
| Sender name in messages | `<strong>.textContent = packet.sender` |
| Filename display | `<div>.textContent = displayName` |
| Reply preview | `<span>.textContent = _rText` |
| Username in user list | `<div>.textContent = u.name` |
| Group name in rooms list | `<div>.textContent = g.name` |
| Toast message | `<div>.textContent = message` |
| Reaction tooltip usernames | Set via `setAttribute('title', ...)` |
| Admin chat viewer messages | `<div>.textContent = decrypted content` |
| All table cells with usernames | `<td>.textContent = username` |

## 8. Sinks That Will Use `createElement` + `appendChild`

| Sink | What changes |
|---|---|
| Entire `buildMessageHtml()` | Convert to function that creates DOM tree and returns document fragment |
| `renderRoomsList()` | Build each room item with createElement instead of HTML string |
| `user_list` handler chatBtn | Build inner structure with createElement instead of innerHTML |
| Admin table rows | Build each row with createElement + textContent cells |

## 9. Sinks That Require DOMPurify

**NONE.** All user data can be rendered via `textContent` or `setAttribute`.
