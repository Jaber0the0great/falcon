# Version 1.1 — Feature Roadmap

> **Order is strict.** Complete each phase in sequence. Do not start a phase until the previous phase is fully verified.
>
> Before implementing any phase: scope, risks, migration requirements, and rollback strategy will be presented for approval.

---

## Execution Order

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6 ──► Phase 7
DB Import   DB Export   Online      Voice Call  Responsive  UX Polish   Ops &
Wizard      & Backup    User Logic  Improve-    & Adaptive              Maintenance
                                    ments       UI
```

---

## Phase 1 — Database Import / Migration Wizard

### Objective
Replace the current CLI-only `utils/migration.py` with a web-based import wizard accessible from the admin dashboard, adding schema validation, conflict resolution options, and a preview step before committing.

### Scope

**Current state:**
- `utils/migration.py:141` — standalone CLI script that searches hardcoded paths for `chat_history.db`, auto-discovers users (sets default password `"password123"`), and migrates messages
- No web UI, no preview, no conflict resolution, no schema validation
- Supports only one legacy schema (no selectable source)
- Default password is hardcoded, not configurable

**Work:**

1. **Web wizard UI** — New route(s) in `routes/admin.py` with Jinja2 wizard template:
   - Step 1: Source selection — file upload (SQLite DB) or server path input
   - Step 2: Schema mapping — detect legacy schema, let admin map columns if names differ
   - Step 3: Preview — show sample of users, messages (counts only, not full content)
   - Step 4: Conflict resolution options:
     - Skip existing usernames (keep existing)
     - Overwrite existing users (reset password)
     - Prefix imported usernames (e.g., `legacy_<name>`)
   - Step 5: Execute — run migration with progress indicator, show result summary

2. **Backend migration engine** — Refactor `utils/migration.py` into `utils/migration/` package:
   - `scanner.py` — detect `chat_history.db`-compatible databases; extract schema metadata
   - `importer.py` — core import logic (users + messages), pluggable into both CLI and web
   - `resolver.py` — conflict resolution strategies (skip, overwrite, prefix)
   - `validator.py` — schema validation (required columns, data types, integrity checks)
   - Keep CLI entry point at `scripts/migrations/legacy_import.py` using the same engine

3. **Configurable defaults** — Read default password for migrated users from `MIGRATION_DEFAULT_PASSWORD` env var (fallback to a randomly generated one that's logged once on first use)

4. **Post-migration summary** — Log counts of users created, users skipped, messages imported, messages skipped (duplicates), errors encountered

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `utils/migration.py` | Refactor | Split into `utils/migration/` package |
| `utils/migration/__init__.py` | New | Package init, expose public API |
| `utils/migration/scanner.py` | New | DB detection, schema discovery |
| `utils/migration/importer.py` | New | Core import logic (users + messages) |
| `utils/migration/resolver.py` | New | Conflict resolution strategies |
| `utils/migration/validator.py` | New | Schema validation, integrity checks |
| `routes/admin.py` | Modify | Add wizard routes (GET/POST) |
| `templates/admin/migration_wizard.html` | New | Multi-step wizard UI |
| `scripts/migrations/legacy_import.py` | New | CLI entry point using new engine |
| `config.py` | Modify | Add `MIGRATION_DEFAULT_PASSWORD` config |
| `.env.example` | Modify | Document new env var |

### Complexity
**Medium** — 4 new modules + 1 new template + route changes. Core logic already exists in `utils/migration.py` and can be extracted, not written from scratch.

### Risks
- **Backward compatibility of the old CLI script** — existing users who run `python utils/migration.py` directly must see a deprecation notice pointing to `python -m scripts.migrations.legacy_import`
- **Large imports** — a legacy DB with 100k+ messages could time out in a web request. Either use async task or process in batches of 1000 with progress updates via SSE or polling
- **File upload size** — the legacy SQLite DB could be hundreds of MB. Set a generous but protected limit (e.g., 200MB) or prefer server-path-based import for large databases
- **Schema drift** — the legacy schema may vary across versions. The validator must be lenient with optional columns

### Dependencies
- None on other V1.1 phases

### Regression Risk
**Low** — existing migration CLI continues to work (with deprecation notice). No changes to user-facing chat or admin features.

### Testing Strategy
1. Create a synthetic legacy `chat_history.db` with known data (3 users, 20 messages, varied types)
2. Test all 3 conflict resolution strategies
3. Test with malformed/missing columns (validator must reject gracefully)
4. Test with empty DB (no users, no messages)
5. Test CLI deprecation notice still works
6. Verify web wizard end-to-end with Playwright or manual steps

### Rollback Strategy
- Revert changes to `routes/admin.py` and `config.py`
- Delete new files under `utils/migration/`
- Keep old `utils/migration.py` intact (it is not deleted, only split)
- No database impact

---

## Phase 2 — Database Export / Backup

### Objective
Add web-based export of chat history (per-user or full), automated backup scheduling, and backup management (list, download, restore, prune) through the admin dashboard.

### Scope

**Current state:**
- `backups/` directory exists with README, is gitignored
- `encrypt_migration.py` has `backup_database()` function that creates `.backup.*` files using SQLite backup API
- No web UI for backup/export
- No scheduled backups
- No backup management (list, prune, restore)

**Work:**

1. **Chat history export** — New route(s) in `routes/admin.py` + admin template:
   - Export all messages as JSON or CSV
   - Filter by user (select target user), date range, message type
   - Export user list with metadata (username, status, last_seen, created_at)
   - Stream large exports to avoid memory issues

2. **Backup engine** — Create `utils/backup.py`:
   - `create_backup()` — copy current DB to `backups/` with timestamped filename, encrypt if `ENCRYPTION_KEY` is set
   - `list_backups()` — return sorted list of backup files with metadata (size, date, type)
   - `restore_backup(filename)` — restore DB from a backup file (admin-only, with confirmation dialog)
   - `prune_backups(retain_count=10)` — delete oldest backups beyond retention limit
   - Integrate with `encrypt_migration.py`'s backup approach (SQLite backup API for consistency, not file copy)

3. **Backup scheduler** — Background thread in `app.py`:
   - Daily backup at configurable time (default: 03:00 AM)
   - Configurable retention (default: keep last 7 backups)
   - Log backup success/failure
   - Skip if no changes since last backup (compare DB file mtime)

4. **Backup management UI** — Admin dashboard section:
   - List backups with filename, date, size, type (manual/scheduled)
   - Download backup file
   - Restore with confirmation modal ("This will replace all current data. Are you sure?")
   - Delete individual backups
   - Configure retention and schedule settings

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `utils/backup.py` | New | Backup engine (create, list, restore, prune) |
| `routes/admin.py` | Modify | Add export and backup management routes |
| `templates/admin/backup_management.html` | New | Backup list, restore, config UI |
| `templates/admin/admin_dashboard.html` | Modify | Add backup tab/section to nav |
| `config.py` | Modify | Add `BACKUP_RETENTION`, `BACKUP_SCHEDULE` config |
| `app.py` | Modify | Spawn backup scheduler background thread |
| `.env.example` | Modify | Document backup-related env vars |

### Complexity
**Medium** — backup engine is straightforward (file operations + SQLite backup API). Export requires streaming JSON/CSV generation. Scheduler is a background thread similar to the existing broadcast poller.

### Risks
- **Restore is destructive** — replaces current database. Must require two-step confirmation and ideally create a pre-restore backup automatically
- **Large exports** — full chat export with millions of messages could generate GB-sized files. Stream in chunks, set a reasonable row limit with pagination, or compress (zip/gzip)
- **Concurrent access** — backup while the app is running (SQLite allows this via backup API, but WAL mode helps). Ensure no data corruption
- **Disk space** — automated backups can fill the disk if retention is misconfigured. Default to 7 backups with a hard cap of 30

### Dependencies
- None on other V1.1 phases

### Regression Risk
**Low** — backup engine is additive; no existing functionality changes. The scheduler background thread follows the same pattern as the broadcast poller.

### Testing Strategy
1. Unit tests for `utils/backup.py`: create backup, verify file exists, restore to temp DB, verify integrity, prune
2. Export test: export user messages as JSON, validate structure and content
3. Scheduler test: mock clock, verify backup runs at configured time
4. Manual: full backup → restore cycle on development DB

### Rollback Strategy
- Remove backup scheduler from `app.py`
- Revert route additions in `routes/admin.py`
- Delete `utils/backup.py`
- Backup files left in `backups/` are harmless but can be cleaned manually
- Database unchanged

---

## Phase 3 — Online User Logic

### Objective
Improve the online presence system: server-side sorting of user lists, meaningful "Online" section separation, proper Busy/Offline visual distinction, last_seen display improvements, and reduction of broadcast overhead.

### Scope

**Current state:**
- `broadcast_user_list()` at `sockets/events.py:106` sends EVERY user to EVERY online user (O(n²) messages)
- Sorting is entirely client-side: online users first, then by last_message_time, then alphabetical
- "Online" = `status != 'Offline'` (both `Available` and `Busy` count)
- `Busy` users show grey dot with "Offline. Last seen..." text — same as truly offline users
- `VALID_STATUS_VALUES` = `Available`, `Busy`, `Offline`
- No "Online users first" heading/section in the rendered UI
- No `last_seen`-based sorting option in the UI
- The `user_list` Socket.IO event sends all users to every online recipient individually

**Work:**

1. **Server-side user list sorting** — Move sorting logic from client (`app.js`) to server (`broadcast_user_list()`):
   - Sort: online users (Available first, then Busy) → offline users (by last_seen descending)
   - Send a single `sorted_users` array per recipient
   - Include `sort_order` metadata so the client doesn't re-sort

2. **UI sections for online status** — Update `chat.html` user list rendering:
   - "Online" heading with count badge (e.g., "Online — 3")
   - "Offline" heading (collapsible, default collapsed if >10 offline users)
   - Busy users show orange/yellow dot with "Busy" label, not grey
   - Currently selected user stays highlighted regardless of section

3. **last_seen display** — Show relative timestamps for offline users:
   - "Last seen 2 minutes ago"
   - "Last seen yesterday at 3:45 PM"
   - "Last seen 3 days ago"
   - "Last seen a long time ago" (>30 days)
   - Use a helper function in JS for formatting, not server timestamps

4. **Busy status visual fix** — Current bug: Busy users show grey dot + "Offline" text. Fix:
   - Busy = orange/yellow status indicator
   - Show "(Busy)" instead of "Offline" in the user list subtitle
   - Messages to a Busy user should still be delivered (they're online), just not trigger notification sounds on their end

5. **Broadcast optimization** — Reduce O(n²) to O(n):
   - Instead of emitting a personalized `user_list` to each online user, emit a single global `user_list` with a frozen snapshot of all users (this is acceptable if every client already receives all users — they do)
   - Only send the full list on join/leave/status_change events (no periodic broadcast)
   - Unread counts can be fetched on-demand via a REST endpoint (`GET /api/unread_counts`) instead of bundled in every user_list broadcast
   - OR keep the current per-user broadcast but only when `unread_count` actually changes

6. **Add `last_seen` ordering toggle** — A small button/dropdown in the sidebar header:
   - "Sort by status" (default) — online first, then last_seen
   - "Sort by last_seen" — all users by last_seen descending regardless of status
   - "Sort alphabetically" — A-Z
   - Preference stored in `localStorage`

7. **`status_update` rate limit** — Already exists at 3/s (in `constants.py:161`). Verify it works:
   - `_check_rate_limit('status_update', user.id)` is called at `events.py:404` — good
   - Could be tightened to 1/5s per user (status updates don't need to be frequent)

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `sockets/events.py` | Modify | Server-side sorting, broadcast optimization |
| `static/js/app.js` | Modify | Update user list rendering with sections, last_seen formatting, sort toggles |
| `static/css/style.css` | Modify | Add orange/yellow Busy indicator, section headings, collapsible styles |
| `templates/chat.html` | Modify | Update user list template structure, add sort controls |
| `utils/security/constants.py` | Modify | Tighten `status_update` rate limit |

### Complexity
**Low-Medium** — mostly frontend logic changes. The server-side sort is a rearrangement of existing data. The Busy status fix is a one-line change. Broadcast optimization is the trickiest part and should be verified with the benchmark script.

### Risks
- **Broadcast optimization regression** — removing per-user broadcasts could break unread count updates for users who don't fetch on-demand. Must ensure unread counts still appear promptly
- **UI section change confusion** — existing users accustomed to a flat user list may be disoriented by sections. Add a smooth transition (CSS animation on first load)
- **Busy behavior change** — if Busy users currently receive no messages (because they're treated as offline somewhere), fixing that could cause unexpected notifications. Audit all message delivery paths
- **last_seen formatting** — relative timestamps must handle timezone differences correctly. The server sends UTC ISO timestamps; the client formats locally

### Dependencies
- None on other V1.1 phases

### Regression Risk
**Medium** — user list rendering touches core UX. Every user interaction depends on the user list being correct. The current flat list is simple; sections add complexity.

### Testing Strategy
1. Unit test: verify server-side sort order (Available > Busy > Offline by last_seen)
2. Integration test: connect 3 users with different statuses, verify each sees the correct sorted list
3. Manual: set status to Busy, verify orange dot + "Busy" label in other clients
4. Manual: verify offline user's last_seen shows correct relative time
5. Benchmark: run `scripts/benchmarks/benchmark_broadcast.py` before and after optimization, verify reduction in emit count
6. Verify sort toggle persists across page reloads (localStorage)

### Rollback Strategy
- Revert all changes — sorting returns to client-side, Busy shows grey dot, sections removed
- No database impact
- User list will briefly show old format until next `user_list` event (within seconds)

---

## Phase 4 — Voice Call Improvements

### Objective
Make WebRTC configuration production-ready: move STUN/TURN to config/env, support proper TURN credential management, improve call UI feedback, and harden error handling.

### Scope

**Current state:**
- 5 Google public STUN servers are hardcoded in `routes/api.py:275-280` and `webrtc.js:33-40` (fallback)
- TURN uses `openrelay.metered.ca:80` with public credentials (`openrelayproject`/`openrelayproject`) — anyone can use these
- `/api/webrtc_config` at `routes/api.py:262-298` returns the ICE configuration
- No TURN credential time-limiting
- Audio-only calls (no video)
- Group calls use mesh topology (each peer connects to every other peer)
- UI: basic call UI with accept/reject/end buttons, minimal error feedback
- No adaptive bitrate or quality adjustments

**Work:**

1. **STUN/TURN via env vars** — Move ICE server configuration to `.env`:
   ```
   STUN_SERVERS=stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302
   TURN_SERVER=turn:your-turn-server.com:3478
   TURN_USERNAME=your-username
   TURN_CREDENTIAL=your-credential
   TURN_CREDENTIAL_SECRET=   # optional: for time-limited credentials
   ```
   - `config.py` parses these into a list
   - No hardcoded fallback to public Google STUN (production should configure their own)
   - Development default: comment out TURN lines, use only STUN (works for LAN)

2. **Remove fallback to hardcoded Google STUN in JS** — `webrtc.js:33-40` currently has a fallback with 5 Google STUN servers if `/api/webrtc_config` fails. This makes the app dependent on Google services. Change to:
   - If API fails, show a warning but attempt call with empty config (browser has built-in STUN discovery via mDNS)
   - Add a UI indicator: "Call quality may be limited — STUN/TURN not configured"

3. **Time-limited TURN credentials** — If `TURN_CREDENTIAL_SECRET` is set:
   - Generate time-limited TURN credentials using HMAC (standard `turn_<timestamp>:<username>` format)
   - Credentials expire after 24 hours
   - Document how to set up coturn with `turnadmin` for secret-based auth

4. **Call UI polish**:
   - Incoming call notification persists until accepted/declined or caller hangs up (currently auto-dismisses after ~30s? verify)
   - Show caller's status (Available/Busy) in call notification
   - Call duration timer starts when call connects (not when dialing)
   - Mute/unmute button with visual indicator
   - Speaker toggle (speakerphone vs earpiece)
   - Connection quality indicator (good/fair/poor/dropped) based on ICE connection state
   - Error messages for common failures: "User is busy", "User is offline", "Call rejected", "Network error"

5. **Call error handling**:
   - Handle ICE disconnection gracefully: show "Reconnecting..." overlay, attempt ICE restart
   - Handle media device errors (mic permission denied, no mic) with clear instructions
   - Timeout for unanswered calls (configurable, default 60s)
   - Proper cleanup on call error (release media tracks, close peer connections)

6. **Group call stability**:
   - Currently mesh topology: N users = N(N-1)/2 peer connections. For 5+ users this degrades quickly.
   - Document the limitation in the UI: show participant count, warn when >4 participants
   - Add "Leave call" confirmation for group calls
   - Fix any group call signaling race conditions (check `group_call_*` event handlers)

7. **Audio input device selection** — Let users choose mic in call settings (dropdown in sidebar or call UI):
   - `navigator.mediaDevices.enumerateDevices()` → populate audioinput select
   - Persist preference in `localStorage`

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `routes/api.py` | Modify | Read STUN/TURN from config, generate time-limited creds |
| `config.py` | Modify | Add STUN_SERVERS, TURN_* config vars |
| `.env.example` | Modify | Document ICE server env vars |
| `static/js/webrtc.js` | Modify | UI polish, error handling, device selection, quality indicator |
| `templates/chat.html` | Modify | Call UI improvements, device selector, quality indicator |
| `static/css/style.css` | Modify | Call UI styles (quality indicator, reconnect overlay) |
| `sockets/events.py` | Modify | Group call signaling fixes |

### Complexity
**Medium-High** — the WebRTC code is already 825 lines and touches real-time audio, which is hard to test automatedly. UI polish is straightforward but error handling requires careful state management.

### Risks
- **WebRTC is hard to test** — most changes require manual testing with 2+ browser tabs or devices
- **Time-limited credentials add complexity** — if `TURN_CREDENTIAL_SECRET` is set but coturn isn't configured, calls will fail. Must validate at startup and log a clear error
- **Device selection** — `enumerateDevices` requires `getUserMedia` permission first (per-spec). The first call must request media, then populate the list
- **Audio quality** — cannot be improved without switching to a selective forwarding unit (SFU) or using a service like LiveKit. This phase explicitly avoids architectural changes to group call topology

### Dependencies
- None on other V1.1 phases

### Regression Risk
**Medium** — WebRTC call flow is complex and any change to signaling or peer connection setup could break existing call functionality. Each change must be manually verified with a 2-tab call test.

### Testing Strategy
1. Manual: 2-tab call test (Chrome + Firefox) — verify call connects, audio flows, end call
2. Manual: incoming call notification, accept, reject, ignore
3. Manual: mute/unmute, verify indicator changes on both ends
4. Manual: group call with 3 tabs, verify all participants can hear each other
5. Manual: kill one participant, verify others see disconnect
6. Error cases: deny mic permission, try calling offline user, try calling self
7. Config validation: run with TURN_CREDENTIAL_SECRET but no coturn → log warning, fall back to STUN-only

### Rollback Strategy
- Revert all changes — STUN returns to hardcoded Google servers, TURN returns to public openrelay
- No database impact
- Ongoing calls will be disrupted if server-side config changes mid-call (acceptable — next call picks up old config)

---

## Phase 5 — Responsive & Adaptive UI

### Objective
Make the main chat and admin dashboard fully responsive across devices (phone, tablet, desktop) with dynamic units, proper breakpoints, touch-friendly interactions, and consistent visual scaling.

### Scope

**Current state:**
- Chat has ONE mobile breakpoint at 991.98px (`chat.html:494`) — sidebar becomes full-width, chat pane overlays
- Admin dashboard has zero custom responsive CSS — relies on Bootstrap grid
- `style.css` has ONE media query (768px for message width)
- Fixed pixel values throughout: sidebar `width: 350px` (chat) and `width: 260px` (admin), emoji picker `320px`
- Fixed fonts: all in `px`, no `clamp()` or `rem` scaling
- `height: 100vh` used instead of `100dvh` (ignores dynamic browser toolbar on mobile)
- No `text-wrap: balance` on headings
- Emoji grid: `repeat(7, 1fr)` without `min-width: 0` — emojis may overflow on small screens
- Chat layout uses flexbox (good foundation)
- Images/videos not consistently `max-width: 100%`
- No touch-specific interactions (long-press for context menu, swipe gestures)
- Call UI doesn't adapt to small screens (buttons overlap, labels truncate)

**Work:**

1. **Mobile-first foundation** — Convert the chat layout to mobile-first CSS:
   - Default: single-column (full-width sidebar), JS-based navigation between sidebar and chat
   - Tablet (≥768px): sidebar 300px, chat fills remaining width
   - Desktop (≥1200px): sidebar 350px (with option to resize)
   - Use `min-width` media queries (mobile-first) instead of `max-width` (desktop-first)

2. **Dynamic units** — Replace fixed pixel values:
   - Font sizes: use `clamp()` for fluid typography (e.g., `clamp(0.875rem, 2vw, 1rem)`)
   - Sidebar: `width: min(350px, 30vw)` or similar responsive calculation
   - Spacing: use `rem` or `clamp()` instead of fixed px
   - `height: 100dvh` (with `100vh` fallback for older browsers) throughout all full-height containers

3. **Admin dashboard responsive** — Add custom responsive breakpoints alongside Bootstrap:
   - `<768px`: sidebar becomes top nav with hamburger menu, content full-width
   - `768px-1200px`: sidebar collapses to icon-only (wide enough for labels), content adjusts
   - Tables: use horizontal scroll on small screens (Bootstrap `.table-responsive` already exists — verify all tables use it)
   - Stats cards: 2-column on tablet, 1-column on phone (currently fixed 3-column grid)
   - Modal dialogs: full-screen on mobile, centered overlay on desktop

4. **Emoji picker responsive** — Fix the emoji grid:
   - Currently `repeat(7, 1fr)` without `min-width: 0` — on small screens emojis get squeezed
   - Use `repeat(auto-fill, minmax(32px, 1fr))` with a container query or media query
   - Fixed `width: 320px` → `min(320px, 90vw)`
   - Ensure emoji picker is touch-scrollable
   - Add search bar that works on mobile (currently search is desktop-only? verify)

5. **Touch interactions**:
   - Long-press on message → show context menu (currently click/hover only)
   - Swipe on user list items → mark as read / delete conversation (optional, stretch goal)
   - Larger touch targets: minimum 44x44px for all interactive elements (buttons, icons, clickable items)
   - Active/focus states that work with touch (not just hover)

6. **Call UI responsive**:
   - Incoming call notification: full-width banner on mobile, centered card on desktop
   - Call controls: bottom-aligned bar with large touch-friendly buttons (50x50px min)
   - Call status text: truncate long usernames with ellipsis
   - Quality indicator: compact on mobile (just a dot), full label on desktop

7. **Media consistency**:
   - All images in messages: `max-width: 100%; height: auto; border-radius: 8px;`
   - Video messages: `max-width: 100%; border-radius: 8px;`
   - File attachments: truncate long filenames with `text-overflow: ellipsis` (already in `style.css:107`)
   - Voice messages: `max-width: 100%` (already in `style.css:97`)

8. **Typography**:
   - Add `text-wrap: balance` to headings and labels (`<h1>`–`<h6>`, `.sidebar-header h5`, etc.)
   - System font stack in `base.html` already includes `Inter` — ensure it loads on all platforms
   - Line-height: `1.5` for body text (currently `1.4` in messages), `1.2` for headings

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `templates/chat.html` | Modify | Mobile-first structure, touch targets, responsive call UI |
| `templates/admin/admin_dashboard.html` | Modify | Responsive sidebar, hamburger nav, full-screen modals |
| `templates/base.html` | Modify | Viewport meta, font loading |
| `static/css/style.css` | Modify | Dynamic units, dvh, clamp(), responsive emoji picker |
| `static/js/app.js` | Modify | Touch interactions, emoji picker responsive search |

### Complexity
**Medium** — large number of files changed, but each change is small (CSS values, class names, attribute adjustments). The admin responsive work is the most complex (currently 1462-line template with 860+ lines of inline JS).

### Risks
- **Mobile-first switch breaks existing desktop** — if `min-width` queries are incorrectly ordered, desktop layout may inherit mobile styles. Must use `min-width` in ascending order with proper specificity
- **100dvh fallback** — Safari iOS uses `100dvh` differently than Chrome. Test on iOS Safari specifically
- **Touch interactions overwrite click handlers** — long-press must not fire the normal click event. Use a timer-based approach (250ms threshold) or use `pointerdown`/`pointerup` events
- **Admin template size** — 1462 lines with inline JS styling is fragile. Consider abstracting admin JS into a separate file as part of this work
- **Performance on mobile** — glassmorphism effects (backdrop-filter: blur) are GPU-intensive on mobile. Test on mid-range Android devices

### Dependencies
- Phase 3 (Online User Logic) changes to the user list HTML may conflict with Phase 5 layout changes. Either:
  - Merge carefully (both change `templates/chat.html` user list section)
  - OR do Phase 3 first and Phase 5 accounts for those changes
  - **Recommendation:** Phase 5 is last, so it will incorporate Phase 3's user list structure

### Regression Risk
**High** — every page's layout changes. Any CSS change can have unexpected side effects across the entire application. Must visually verify every page at 3 breakpoints (phone 375px, tablet 768px, desktop 1440px).

### Testing Strategy
1. Visual regression: screenshot comparison at 375px, 768px, 1024px, 1440px for:
   - Login page
   - Chat page (with messages, user list, call UI)
   - Admin dashboard (each tab: stats, users, groups, messages, media, broadcast)
2. Interactive testing on actual mobile device or Chrome DevTools device emulation:
   - User list tap → opens chat
   - Back button → returns to user list
   - Send message, attach file, record voice
   - Incoming call notification, accept/reject
   - Emoji picker open/close, select emoji
3. Touch test: long-press message → context menu appears on phone
4. Admin: verify hamburger menu works, all tabs accessible on 375px
5. Verify all modals are scrollable on small screens
6. Performance: check for layout shifts (CLS) and sticky hover states on touch devices

### Rollback Strategy
- Revert all CSS and template changes
- Desktop layout returns to current fixed-pixel design
- Touch interactions removed
- No database impact
- This is the highest-rollback-risk phase due to the number of files changed

---

## Phase 6 — UX Polish

### Objective
Improve the overall user experience without changing business logic.

### Scope

**Current state:**
- Loading states: minimal — some buttons show spinners, most operations have no visual feedback
- Skeleton screens: none — content appears abruptly once loaded
- Empty states: missing — "No messages yet", "No users found" etc. are absent or inconsistent
- Toast notifications: mixed — uses both Flask `flash()` (page-level) and custom inline notifications (Socket.IO). No unified toast component
- Animations: message sending has a brief flash (`highlight-flash` in `chat.html:492`), user items have `transition: background 0.2s`, context menu fades in. No page transitions, no sidebar slide, no modal entrance animation
- Keyboard shortcuts: none — all interactions require mouse/touch
- Accessibility: no ARIA labels, no focus management, no skip-to-content link, no screen-reader-friendly markup
- Mobile interactions: tap targets are inconsistently sized, no swipe gestures, no pull-to-refresh
- Desktop interactions: no right-click context menus outside messages, no drag-and-drop file upload (only click-to-browse)
- Visual consistency: button styles vary (some have `border-radius: 20px`, others `8px`), icon sizes differ, spacing is inconsistent

**Work:**

1. **Loading states** — Standardized loading pattern for all async operations:
   - Button loading: disable button + show spinner + prevent double-submit (already done for some buttons, audit and unify)
   - Page/panel loading: overlay with centered spinner + "Loading..." text (use a shared CSS class `.loading-overlay`)
   - List loading: nth-child shimmer animation for user list, message list, group list
   - Image loading: low-res placeholder blur-up (`background: rgba(255,255,255,0.05)` + `loading="lazy"`)

2. **Skeleton screens** — Replace abrupt content loading with skeleton placeholders:
   - User list sidebar: 8 skeleton rows (avatar circle + 2 text lines with shimmer animation)
   - Message area: 5 skeleton bubbles (alternating left/right alignment with shimmer)
   - Admin dashboard stats: 4 skeleton cards with shimmer
   - Admin tables: 6 skeleton rows
   - CSS-only, no JS library — use `@keyframes shimmer` with `background: linear-gradient(...)`

3. **Empty states** — Every list/panel must show a helpful message when empty:
   - "No conversations yet. Start by selecting a user to chat with." (user list when no chats)
   - "No messages here yet. Say hello!" (message area)
   - "No users found matching your search." (search with no results)
   - "No groups yet. Create your first group." (group list)
   - "No broadcasts sent yet." (admin broadcast history)
   - Each empty state gets an icon (Bootstrap Icons) + heading + description + optional CTA button
   - Use a shared `.empty-state` CSS class

4. **Toast notification unification** — Replace all ad-hoc notifications with a single toast system:
   - Use Bootstrap 5 Toasts (already available via Bootstrap dependency)
   - All notifications go through a single JS function: `showToast(message, type, duration)`
   - Types: `success` (green), `error` (red), `warning` (yellow), `info` (blue)
   - Default duration: 5s for info, 8s for error (persistent until dismissed)
   - Position: bottom-right on desktop, top-full-width on mobile
   - Socket.IO events (`system`, `message_status`, etc.) also use this toast system
   - Remove all `alert()` calls, inline `div` flash messages, and custom notification HTML

5. **Better animations** — CSS animations for common interactions:
   - Page/section transitions: `opacity 0.2s ease` + `transform: translateY(0)` on content panels
   - Sidebar slide: `transform: translateX(0)` with easing on mobile sidebar toggle
   - Message appear: slide-up + fade-in on new messages (`.message-enter` animation)
   - User list status change: brief green pulse when user comes online, grey fade when offline
   - Modal entrance: scale + fade (Bootstrap already does this, verify consistency)
   - Button hover: subtle scale(1.02) + shadow lift for primary actions
   - All animations respect `prefers-reduced-motion` media query — disable all non-essential motion

6. **Keyboard shortcuts** — Define and implement a keyboard navigation layer:
   - `Ctrl+K` or `/` — focus search bar
   - `Ctrl+N` — new conversation (focus first user in list)
   - `Ctrl+Shift+N` — new group (open create group modal)
   - `Escape` — close modal / context menu / emoji picker / call
   - `Arrow Up/Down` — navigate user list
   - `Enter` — select highlighted user / send message
   - `Ctrl+Enter` — send message (alternative, useful with multiline input)
   - `Ctrl+Shift+M` — mute/unmute in active call
   - `Ctrl+Shift+E` — end active call
   - Show available shortcuts with `?` key (open shortcuts modal)
   - Document shortcuts in a settings/help panel
   - Only active when not focused in an input/textarea

7. **Accessibility (ARIA, focus order, tab navigation)**:
   - Add `role` attributes: `role="tablist"` to sidebar, `role="tab"` to user items, `role="log"` to message area, `role="alert"` to toasts
   - Add `aria-live="polite"` to message list (screen reader announces new messages)
   - Add `aria-live="assertive"` to toast container
   - Add `aria-label` to all icon-only buttons (call, attach, emoji, send, mute, etc.)
   - Add `aria-expanded` to collapsible elements (group list, offline users section)
   - Add `aria-current="page"` to active nav items in admin panel
   - Add `aria-hidden="true"` to decorative icons
   - Add `tabindex="0"` to clickable divs (user items, message options) — or use `<button>` elements
   - Ensure logical focus order: sidebar → message list → input → actions (tab through the page)
   - Add skip-to-content link as the first focusable element (hidden until focused)
   - Add focus trap in modals (tab cycles within modal, Shift+Tab goes backwards)
   - Add `role="dialog"`, `aria-modal="true"`, `aria-labelledby` to all modals
   - Ensure color contrast meets WCAG AA minimum (4.5:1 for text, 3:1 for large text)
   - Test with screen reader (NVDA or VoiceOver) on core flows: login → select user → send message → receive reply

8. **Better mobile interactions**:
   - Tap targets: minimum 44x44px for all interactive elements (audit buttons, icons, links)
   - Swipe to delete conversation: swipe user list item left → show "Delete" button
   - Pull-to-refresh: on message list, pull down to load recent messages (uses existing history API)
   - Long-press on message: show context menu (currently desktop-only hover)
   - Prevent zoom on double-tap: `touch-action: manipulation` on chat area
   - Bottom sheet for actions on mobile instead of dropdown menus (context menu becomes bottom sheet)
   - Haptic feedback on supported devices (use `navigator.vibrate()` for call connect/disconnect)

9. **Better desktop interactions**:
   - Right-click context menu on user items: "Send message", "View profile", "Block" (future)
   - Right-click context menu on empty chat area: "Reload messages", "Clear chat", "Mark as read"
   - Drag-and-drop file upload: drag file onto chat area → show drop zone overlay with "Drop to send" text
   - Double-click to edit sent message (within 5-minute window, if the feature exists)
   - Resizable sidebar: drag the right edge of the sidebar to resize (persist width in localStorage)
   - Middle-click to open user in new tab (if multi-window support is desired)

10. **Visual consistency audit**:
    - Button styles: unify `border-radius` (all primary buttons: `10px`, all icon buttons: `50%`)
    - Icon sizes: use `font-size` classes consistently (`.icon-sm: 16px`, `.icon-md: 20px`, `.icon-lg: 24px`)
    - Spacing: use a spacing scale based on `4px` increments (4, 8, 12, 16, 20, 24, 32, 40, 48, 64)
    - Colors: audit all inline `color`/`background` values and replace with CSS custom properties (already started with `:root` in `style.css` and `chat.html`)
    - Shadows: use a shadow scale (`.shadow-sm`, `.shadow-md`, `.shadow-lg`) consistently
    - Font weights: 500 for labels/headings, 400 for body, 600 for active/selected states
    - Border radius: use a scale (`.radius-sm: 6px`, `.radius-md: 10px`, `.radius-lg: 16px`, `.radius-full: 50%`)

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `static/css/style.css` | Modify | Loading states, skeleton screens, empty states, animations, visual consistency |
| `static/js/app.js` | Modify | Toast system, keyboard shortcuts, drag-drop upload, swipe interactions |
| `static/js/socket.js` | Modify | Route system events through toast system |
| `templates/chat.html` | Modify | ARIA attributes, skip-to-content, skeleton markup, empty states, touch targets |
| `templates/base.html` | Modify | Toast container, skip-to-content link, viewport meta |
| `templates/admin/admin_dashboard.html` | Modify | ARIA attributes, loading states, empty states |
| `templates/login.html` | Modify | ARIA labels, loading state on submit |
| `templates/register.html` | Modify | ARIA labels, loading state on submit |

### Complexity
**High** — 10 workstreams across the entire frontend. Accessibility audit is particularly broad (every interactive element needs review). Keyboard shortcuts require coordination to avoid conflicts with browser defaults.

### Risks
- **Keyboard shortcut conflicts** — `Ctrl+K` is "focus search bar" in Gmail but in some browsers it opens the bookmark manager. Use `event.preventDefault()` and document conflicts
- **Skeleton screen flash** — if content loads faster than the skeleton animation, users see a flash. Add a minimum display time (300ms) for skeletons
- **ATAG/ WCAG compliance is iterative** — achieving full WCAG AA may require multiple passes. Focus on critical flows for V1.1 (login, message send/receive, user list navigation)
- **Toast flooding** — if multiple system events fire at once, toasts can stack. Limit visible toasts to 3, queue the rest
- **Drag-and-drop** — browser security restricts drag events from file manager. Works on most modern browsers but test on Firefox and Safari

### Dependencies
- Phase 5 (Responsive & Adaptive UI) — the toast positioning and mobile interactions should build on Phase 5's responsive foundation
- Phase 3 (Online User Logic) — the user list sectioning affects skeleton placement

### Regression Risk
**Medium** — toast system replaces all existing notification methods; any missed replacement could cause silent failures. Keyboard shortcuts should not interfere with normal typing (check `event.target` before handling).

### Testing Strategy
1. Visual audit: every page inspected for loading states, empty states, and skeletons
2. Keyboard: navigate entire app using Tab only — verify focus order, skip-to-content, modal trap
3. Screen reader: NVDA/ChromeVox test on login → chat → send → receive flow
4. Toast: trigger every notification type (message sent, error, system broadcast, call notification)
5. Mobile: test tap targets on actual phone (not just DevTools emulation)
6. Animations: test with `prefers-reduced-motion: reduce` — verify no jarring motion
7. Drag-drop: upload file by dragging from file explorer onto chat area

### Rollback Strategy
- Revert CSS, JS, and template changes
- Toast system removed, original `alert()` and inline notifications restored
- Keyboard shortcuts removed
- ARIA attributes removed (no harm in leaving some, but revert all for clean rollback)
- No database impact

---

## Phase 7 — Operations & Maintenance

### Objective
Improve long-term maintainability by adding centralized audit logging, system monitoring, and a maintenance dashboard.

### Scope

**Current state:**
- Audit logging: none — no log of who performed which admin action or when
- Backup history: none — backups exist in `backups/` but no index of when they were created or why
- Restore history: none — no record of database restores
- System health: none — no endpoint or dashboard showing app status, DB size, or uptime
- Database statistics: none — no quick way to see row counts, DB file size, or table sizes
- Storage usage: none — no tracking of how much disk space uploads consume
- Maintenance dashboard: none — all admin stats are scattered across individual tabs

**Work:**

1. **Audit logging** — Create `AuditLog` model and log all sensitive operations:
   ```python
   class AuditLog(db.Model):
       id = db.Column(db.Integer, primary_key=True)
       timestamp = db.Column(db.DateTime, default=datetime.utcnow)
       actor = db.Column(db.String(80), nullable=False)      # username who performed action
       action = db.Column(db.String(50), nullable=False)      # action type: 'user_create', 'user_delete', 'user_ban', 'message_delete', 'broadcast', 'backup', 'restore', 'config_change', 'password_reset', 'import', 'export'
       target_type = db.Column(db.String(50), nullable=True)  # 'user', 'message', 'group', 'system'
       target_id = db.Column(db.String(80), nullable=True)    # username, msg_id, group_name, etc.
       details = db.Column(db.Text, nullable=True)            # JSON blob with action-specific metadata
       ip_address = db.Column(db.String(45), nullable=True)   # actor's IP
       success = db.Column(db.Boolean, default=True)          # whether action succeeded
   ```
   - Log from all admin routes: user create/delete/ban/unban, message delete, broadcast send, backup create/restore/delete, import execute
   - Log from auth routes: login failure (with IP), password reset, registration
   - Log from Socket.IO: no — too high frequency; HTTP admin actions only
   - View audit log in admin dashboard with filters (actor, action, date range)
   - Retention: auto-prune logs older than 90 days (configurable via env var)

2. **Admin action import/export logging** — Specific log entries for:
   - **Import logs**: source filename, total records, users imported/skipped, messages imported/skipped, groups imported/skipped, duration, result (success/partial/failure), error details
   - **Export logs**: export type (full/user/message), filters applied, record count, file size, duration, requester
   - **Backup history**: backup filename, size, type (manual/scheduled), duration, result, triggered by
   - **Restore history**: backup filename used, size, duration, result, triggered by, pre-restore backup auto-created

3. **System health endpoint** — New route `GET /api/health` (no auth required, basic):
   ```json
   {
     "status": "ok",
     "uptime_seconds": 123456,
     "database": {
       "size_mb": 12.5,
       "tables": 7,
       "row_counts": {
         "user": 15,
         "message": 4283,
         "group": 3,
         "group_member": 12,
         "group_invite": 5,
         "group_join_request": 2,
         "system_broadcast": 8,
         "audit_log": 142
       }
     },
     "storage": {
       "uploads_path": "static/uploads/",
       "total_size_mb": 45.2,
       "file_count": 63,
       "largest_file": "recording_20260615_143022.wav",
       "largest_file_size_mb": 8.1
     },
     "version": "1.1.0",
     "python_version": "3.12.4",
     "memory_mb": 78.3
   }
   ```
   - Database size: query `PRAGMA page_count * PRAGMA page_size`
   - Row counts: `SELECT COUNT(*) FROM <table>` for each table
   - Storage: recursively scan `static/uploads/` for total size and file count (cache for 5 minutes)
   - Uptime: track in a module-level variable set at app startup
   - Memory: `psutil` if available, otherwise omit

4. **Database statistics** — Admin dashboard panel showing:
   - Total database file size
   - Row counts per table (with trend: +12 messages today, +2 users this week)
   - Largest tables by row count
   - Message counts by type (`text`, `file`, `voice`, `call_log`, `system`)
   - Message counts by day (last 7 days, as a simple bar or sparkline)
   - User signups per day (last 7 days)
   - Storage usage over time (daily snapshot, stored in a new `StatsSnapshot` table or computed from logs)

5. **Storage usage tracking** — Monitor `static/uploads/`:
   - Total size on disk
   - File count
   - Breakdown by file type (images, audio, documents)
   - Largest files (top 10)
   - Orphaned files (files in uploads/ not referenced by any Message record)
   - Storage trend (size at start of each day — store in `StatsSnapshot`)

6. **Maintenance dashboard** — A new admin tab/section consolidating all ops views:
   - **System Health**: status indicators (green/yellow/red) for: database reachable, storage under threshold, audit logging active, last backup age, background tasks running
   - **Audit Log**: searchable/filterable log with export to CSV
   - **Backup Management**: list of backups with create/restore/delete actions (move from Phase 2)
   - **Database Stats**: table sizes, row counts, daily activity charts
   - **Storage Overview**: disk usage by type, orphaned files list, largest files
   - **Import/Export Logs**: history of all imports and exports with details
   - **Configuration**: current env vars (without secrets), runtime settings

### Files Expected to Change

| File | Change Type | Description |
|------|-------------|-------------|
| `models/models.py` | Modify | Add `AuditLog` model |
| `utils/audit.py` | New | `log_action()` helper, `AuditLog` query wrappers |
| `utils/system_health.py` | New | DB stats, storage scan, health check logic |
| `routes/admin.py` | Modify | Add audit log routes, health panel routes, import/export log routes |
| `templates/admin/maintenance_dashboard.html` | New | Full ops dashboard with all panels |
| `templates/admin/admin_dashboard.html` | Modify | Add "Maintenance" tab link |
| `routes/api.py` | Modify | Add `GET /api/health` endpoint |
| `app.py` | Modify | Start uptime tracker, daily stats snapshot thread |
| `config.py` | Modify | Add `AUDIT_LOG_RETENTION_DAYS`, `STATS_SNAPSHOT_INTERVAL` |
| `.env.example` | Modify | Document new audit/stats env vars |

### Complexity
**Medium-High** — 2 new utility modules, 1 new model, 1 new template, plus changes to admin routes and background tasks. The storage scanner must be efficient (cache results, don't scan on every request).

### Risks
- **Storage scan performance** — scanning `static/uploads/` with 1000+ files on every request would be slow. Cache results for 5 minutes, invalidate on upload/delete
- **psutil availability** — `psutil` is not in `requirements.txt`. Memory reporting is optional; omit if psutil is not installed, log a warning
- **Audit log table growth** — at 100 admin actions/day, 90 days = 9000 rows. Tiny for SQLite. At 1000/day it's 90k rows — still fine. No need for sharding
- **Daily stats snapshot** — creates one row per day in a `StatsSnapshot` table. After 10 years = 3650 rows. Negligible

### Dependencies
- Phase 2 (DB Export & Backup) — the maintenance dashboard's backup management panel replaces/extends Phase 2's backup UI. If Phase 2 is not done yet, the maintenance dashboard includes backup management as a bonus

### Regression Risk
**Low-Medium** — all changes are additive (new models, new routes, new templates). No existing functionality is modified. The health endpoint is new. The background stats thread is similar to the existing broadcast poller pattern.

### Testing Strategy
1. Unit: `AuditLog` model create, query by actor/action/date, auto-prune
2. Integration: perform admin action (ban user) → verify audit log entry created
3. Integration: `GET /api/health` returns valid JSON with all fields
4. Integration: storage scan returns correct file count and size (compare to `Get-ChildItem`)
5. Manual: maintenance dashboard renders all panels, filters work, export CSV works
6. Performance: storage scan on directory with 1000+ files completes under 1 second (cache after first scan)

### Rollback Strategy
- Revert `models/models.py` (AuditLog model removed on next `db.create_all()` — or keep it, table is harmless)
- Remove `utils/audit.py` and `utils/system_health.py`
- Revert routes in `routes/admin.py` and `routes/api.py`
- Remove maintenance dashboard template
- Revert `app.py` background thread changes
- Audit log data remains in the database but is inaccessible — can be cleaned manually with `DROP TABLE audit_log`

---

## Dependency Graph

```
Phase 1 (DB Import Wizard)
    │
    ▼
Phase 2 (DB Export & Backup)     ← Independent of Phase 1
    │
    ▼
Phase 3 (Online User Logic)      ← Independent of Phase 1, 2
    │
    ▼
Phase 4 (Voice Call Improve)     ← Independent of Phase 1, 2, 3
    │
    ▼
Phase 5 (Responsive & Adaptive)  ← Should come after Phase 3 (user list HTML structure)
    │                              Independent of Phase 1, 2, 4
    ▼
Phase 6 (UX Polish)              ← Depends on Phase 5 (toast positioning, mobile interactions)
    │                              Independent of Phase 1, 2, 3, 4
    ▼
Phase 7 (Ops & Maintenance)      ← Depends on Phase 2 (backup management panel)
                                   Independent of Phase 1, 3, 4, 5, 6
```

**Note:** Phases 1–5 as originally designed. Phase 6 builds on Phase 5's responsive foundation. Phase 7 extends Phase 2's backup management.

---

## Estimated Effort

| Phase | Description | Est. Engineering Days | Risk Level |
|-------|-------------|----------------------|------------|
| 1 | DB Import / Migration Wizard | 3-5 | Medium |
| 2 | DB Export / Backup | 2-4 | Medium |
| 3 | Online User Logic | 2-4 | Low-Medium |
| 4 | Voice Call Improvements | 3-6 | Medium-High |
| 5 | Responsive & Adaptive UI | 4-7 | Medium |
| 6 | UX Polish | 5-8 | Medium |
| 7 | Operations & Maintenance | 4-7 | Medium |
| **Total** | | **23-41** | |

---

## Phase Gating Criteria

| Phase | Gate |
|-------|------|
| 1 | All 3 conflict resolution strategies tested. CLI deprecation notice works. Web wizard end-to-end tested. Test suite passes. |
| 2 | Backup create/list/restore/prune tested. Export generates valid JSON/CSV. Scheduler verified. Test suite passes. |
| 3 | Server-side sort order verified. Busy status shows correctly. last_seen formatting accurate. Broadcast benchmark shows improvement. Test suite passes. |
| 4 | 2-tab call test passes. Config validation works. Mute/speaker/device selection functional. Error cases handled gracefully. Test suite passes. |
| 5 | Visual regression passed at 3 breakpoints. Touch interactions work. Admin fully responsive. 100dvh fallback verified. Test suite passes. |
| 6 | Loading states present on all async operations. Toast notifications use single pattern. A11y audit passes (WAVE tool). Keyboard shortcuts documented. Test suite passes. |
| 7 | All admin actions logged. Health endpoint returns system stats. Storage usage tracked. Maintenance dashboard renders all panels. Test suite passes. |
