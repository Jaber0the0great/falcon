# Phase 3A — Presence Backend

> Part of V1.1 Presence System (split from original Phase 3)  
> Backend-only: no frontend/UI changes in this phase  
> Status: **Approved** — ready for implementation

---

## 1. Scope

Implement server-side presence improvements. No HTML, CSS, or client JS changes.

### In Scope

| Area | Description |
|------|-------------|
| Connection registry | In-memory `username → set(sid)` tracking |
| Multi-tab fix | Only set `Offline` on last disconnect |
| Heartbeat handler | Socket `heartbeat` event → refresh `last_seen` |
| `last_seen` accuracy | Updated on heartbeat + connect/disconnect |
| Away detection | Auto-set `Away` after `AWAY_TIMEOUT_SECONDS` of no heartbeat |
| Busy handling | Auto-set `Busy` on WebRTC call start, restore on end |
| Reconnect logic | Preserve previous status across reconnect; no startup reset |
| Debounced broadcasts | `PRESENCE_DEBOUNCE_MS` debounce on presence broadcasts |
| Diff-based updates | `user_update` event replaces full-list broadcasts for status changes |
| Status value expansion | Add `Away` + reserve `Invisible` |
| Presence reason | Internal `presence_reason` column — not exposed to UI |
| Centralized timing | All presence timing constants in `constants.py` |
| Remove startup reset | Do not set all users to `Offline` on app startup |
| Tests | `tests/test_presence.py` covering all backend changes |

### Out of Scope (Phase 3B)

- Status selector dropdown in chat UI
- Status dot colors (green/yellow/red/gray)
- "Last seen" labels
- Collapsible offline users
- Client-side heartbeat sending
- Client-side `user_update` event handling
- Client-side sort changes
- `Invisible` state implementation (reserved only)
- `presence_reason` UI exposure (internal only)

---

## 2. Design Improvements (Pre-Implementation)

### 2.1 Reserved Support: Invisible State

**Requirement:** Reserve `Invisible` as a future presence value. Do not implement its behavior yet. Ensure the architecture can support it later without structural changes.

**Status value set:**
```python
VALID_STATUS_VALUES = frozenset({
    'Available',
    'Busy',
    'Away',
    'Invisible',   # RESERVED — no behavior implemented yet
    'Offline',
})
```

**Architectural pattern for future support:**

The key architectural insight is separation of **connection state** (is the socket connected?) from **visibility** (do other users see this user as online?).

| Concept | Today | With Invisible |
|---------|-------|----------------|
| Connection registry | Tracks SIDs | Tracks SIDs (unchanged) |
| `is_online()` | registry has SID | registry has SID (unchanged) |
| Visible to others | `status != 'Offline'` | `status != 'Offline' && status != 'Invisible'` |
| Receives events | `status != 'Offline'` | All connected users (unchanged) |
| Can send messages | `status != 'Offline'` | All connected users (unchanged) |

To support this in the future:
1. The `_send_user_updates()` function must **filter out `Invisible` users** so others see them as non-existent (or as `Offline`).
2. The `Invisible` user's own client must receive a separate payload confirming their own status (so they know they're invisible).
3. The connection registry does **not** need to change — it tracks TCP/Socket.IO connections, not visibility.

**Changes to make now (reserved, no behavior):**
- Add `'Invisible'` to `VALID_STATUS_VALUES`
- Add a comment in the broadcast filtering logic: `# TODO (Phase 3C): Filter Invisible users from other users' presence views`
- No runtime behavior changes for `Invisible`

### 2.2 Runtime Presence State (Not in Database)

**Requirement:** Support an optional reason string for the current presence state. Examples: `Busy → "In Call"`, `Away → "Idle Timeout"`. Do **not** expose to UI yet.  

**Architectural Decision: Presence is Runtime State.**

Presence metadata (reason, heartbeat timing, connection count) is **transient runtime state** that does not survive restarts. Keeping it out of the database avoids:

- Writes on every heartbeat (every 60s per online user)
- Writes on every tab open/close
- Writes on every status transition
- Schema churn for what is fundamentally ephemeral data

**Persistence model:**

| Data | Location | Written | Survives Restart? |
|------|----------|---------|-------------------|
| `status` | User model (DB) + PresenceRegistry (memory) | On status change | Yes (DB) |
| `last_seen` | User model (DB) | On connect/disconnect/heartbeat | Yes |
| `presence_reason` | PresenceRegistry only | On status change | **No** |
| `last_heartbeat` | PresenceRegistry only | On connect + heartbeat | **No** |
| `connections` (SIDs) | PresenceRegistry only | On connect/disconnect | **No** |

**Why `status` lives in both places:**
- **Database:** Backward compatibility with existing code that reads `user.status` directly (admin panel, API responses, existing socket events).
- **Registry:** Fast in-memory access for presence decisions without a DB round-trip.
- Both are kept in sync: every status change writes to the DB AND updates the registry.

**Auto-set rules for `presence_reason` (registry-only, internal):**

| Status Transition | Reason | Trigger |
|-------------------|--------|---------|
| `Available` → `Busy` | `'in_call'` | `call_start` socket event |
| `Busy` → previous | `'active'` | `call_end` socket event |
| `Available`/`Busy` → `Away` | `'idle_timeout'` | `check_away_users()` timeout |
| `Away` → `Available` | `'active'` | Heartbeat received |
| Any → `Offline` | `'disconnected'` | Last tab disconnect |
| Any → `Available` (connect) | `'active'` | First tab connect (if was Offline) |
| Manual `status_update` | `'manual'` | (reserved for Phase 3B UI) |

**On server restart:** The registry is empty. When users reconnect:
1. DB `status` is loaded into the registry on first connect.
2. DB `status` of `Offline` → transitions to `Available` (user just connected).
3. DB `status` of `Busy` → preserved (user was busy before restart; stays busy).
4. `presence_reason` is `None` (transient metadata is lost — acceptable).

**The `presence_reason` is not included in any socket payload in Phase 3A.** Phase 3B may expose it in UI tooltips/subtitles.

### 2.3 Centralized Timing Constants

**Requirement:** Move all presence timing values into `utils/security/constants.py` instead of hardcoding in event handlers.

```python
# ──────────────────────────────────────────────
# Presence / Status
# ──────────────────────────────────────────────

VALID_STATUS_VALUES: frozenset = frozenset({
    'Available', 'Busy', 'Away', 'Invisible', 'Offline',
})

# How often the client sends a heartbeat (seconds).
# Must match the client-side interval.
HEARTBEAT_INTERVAL_SECONDS: int = 60

# How long without a heartbeat before auto-setting to Away.
# 180s = 3 missed heartbeats at 60s. Tolerates brief network hiccups
# and tab backgrounding while catching idle users within 3 minutes.
AWAY_TIMEOUT_SECONDS: int = 180

# Stale-connection safety net. Must be > AWAY_TIMEOUT_SECONDS.
# 300s = 5 minutes. Catches zombie connections from server crashes.
PRESENCE_TIMEOUT_SECONDS: int = 300

# Debounce window for presence broadcasts (milliseconds).
# Prevents rapid connect/disconnect/status-change from flooding clients.
PRESENCE_DEBOUNCE_MS: int = 500

# How often the background task checks for timed-out users (seconds).
PRESENCE_CHECK_INTERVAL_SECONDS: int = 30
```

**Usage in code:** All references use these constants. No magic numbers.

**Timeout rationale:**

| Constant | Value | Rationale |
|----------|-------|-----------|
| `HEARTBEAT_INTERVAL_SECONDS` | 60 | Aligns with typical keepalive. Frequent enough for responsive Away detection without being chatty. |
| `AWAY_TIMEOUT_SECONDS` | 180 (was 60) | 60s was too aggressive — a single missed heartbeat (page load, brief network pause) would falsely mark Away. 180s = 3 missed beats provides real tolerance. |
| `PRESENCE_TIMEOUT_SECONDS` | 300 (was 120) | Safety net for stale SIDs after crash. Must be comfortably above Away timeout. 300s = 5 min. |
| `PRESENCE_DEBOUNCE_MS` | 500 | Prevents broadcast storms on rapid connect/disconnect. 500ms is imperceptible for presence. |
| `PRESENCE_CHECK_INTERVAL_SECONDS` | 30 | Half of the Away timeout floor. Frequent enough to catch timeouts promptly without CPU churn. |

### 2.4 Complete Presence Lifecycle

**State machine:**

```
                          ┌─────────────────────────────┐
                          │         DISCONNECTED         │
                          │   (no active SID, DB hit)    │
                          └──────────┬──────────────────┘
                                     │
                          Socket connect (first tab)
                          status=Available, reason=active
                          registry.add(sid)
                          debounced_broadcast() → user_update
                                     │
                                     ▼
                          ┌─────────────────────────────┐
            ┌─────────────│        CONNECTED            │─────────────┐
            │             │   Available / Busy / Away   │             │
            │             │  (1+ active SIDs)           │             │
            │             └──────────┬──────────────────┘             │
            │                        │                                │
            │          ┌─────────────┼─────────────┐                  │
            │          │             │             │                  │
            │          ▼             ▼             ▼                  │
            │  ┌───────────┐ ┌───────────┐ ┌───────────┐             │
            │  │ Heartbeat │ │call_start │ │call_end   │             │
            │  │ every 60s │ │Busy+reason│ │restore    │             │
            │  │ updates   │ │='in_call' │ │prev status│             │
            │  │ last_seen │ └───────────┘ └───────────┘             │
            │  │ If Away → │                                         │
            │  │ Available │              ┌──────────────────┐        │
            │  └─────┬─────┘              │ check_away_users │        │
            │        │                    │ runs every 30s   │        │
            │        │                    │ last_seen > 60s  │        │
            │        │                    │ → Away + reason  │        │
            │        │                    │   ='idle_timeout'│        │
            │        │                    └────────┬─────────┘        │
            │        │                             │                  │
            │        └──────────────────┬──────────┘                  │
            │                           │                             │
            │                           ▼                             │
            │              ┌──────────────────────────┐               │
            │              │   PRESENCE_TIMEOUT (120s) │               │
            │              │   (no heartbeat, but SID │               │
            │              │    still active = stale) │               │
            │              │   Future: force Offline  │               │
            │              └──────────────────────────┘               │
            │                                                         │
            │                                                         │
            └────────────────── Socket disconnect (last tab) ─────────┘
                                status=Offline, reason=disconnected
                                registry.remove(sid) → count=0
                                debounced_broadcast() → user_update
                                │
                                ▼
                          ┌─────────────────────────────┐
                          │       OFFLINE (PERSISTED)    │
                          │   status=Offline in DB       │
                          │   last_seen=disconnect time  │
                          └─────────────────────────────┘
```

**Transition table:**

| # | From | To | Trigger | Broadcast | Reason |
|---|------|----|---------|-----------|--------|
| 1 | Offline/any | Available | Socket connect (first tab) | `user_update` | `'active'` |
| 2 | Available/Busy | (same) | Socket connect (extra tab) | None | None |
| 3 | Available | Busy | `call_start` event | `user_update` | `'in_call'` |
| 4 | Busy | previous | `call_end` event | `user_update` | `'active'` |
| 5 | Available/Busy | Away | No heartbeat > 60s | `user_update` | `'idle_timeout'` |
| 6 | Away | Available | Heartbeat received | `user_update` | `'active'` |
| 7 | Any (except Offline) | Offline | Socket disconnect (last tab) | `user_update` | `'disconnected'` |
| 8 | Any | (reserved) | Manual `status_update` | `user_update` | `'manual'` |
| 9 | Away | Offline | `PRESENCE_TIMEOUT` (no heartbeat > 120s, stale SID) | (future) | `'timeout'` |

**Transition 9 is not implemented in Phase 3A** — it's a safety net for stale SIDs (server crash, network partition). The disconnect handler covers the normal case.

### 2.5 Event Model Decision: Keep `user_update`

**Question:** Would dedicated presence events (`presence_online`, `presence_away`, `presence_offline`) simplify the implementation compared to the generic `user_update` event?

**Analysis:**

| Criterion | Dedicated Events (`presence_*`) | Generic Event (`user_update`) |
|-----------|--------------------------------|-------------------------------|
| Event count | 3+ handlers (online/away/offline) | 1 handler with status field |
| Client logic | Simpler per-event handlers (no parsing) | Needs status field switch |
| Extensibility | New status = new event type | New status = new field value (no new event) |
| Payload size | Minimal (just username) | Slightly larger (status + reason fields) |
| Invisible support | Would need `presence_invisible` event (invisible to others = don't send) | Just filter by status before sending |
| Future reasons | Would need separate event or extra field | Already has field slot |

**Decision: Keep `user_update` as the single presence event.**

Rationale:
- Adding a new status (future `Invisible`) requires zero event-model changes — just add the value.
- The `presence_reason` field fits naturally in the existing payload.
- One event is simpler to document, implement, and test.
- The client will already need a status-field switch for the status selector (Phase 3B), so splitting into separate events adds no client-side simplicity.

### 2.6 Artifacts Required After Implementation

After Phase 3A implementation completes, the following must be produced:

1. **Presence lifecycle diagram** — ASCII state machine (see §2.4 above, rendered in final report)
2. **Backend regression report** — Full test output: `191 existing + N new = 191+N passed`
3. **Performance impact** — Measure or estimate:
   - Queries per event (before vs. after)
   - Broadcasts per event (before vs. after)
   - DB write rate from heartbeats
4. **Memory impact** — Estimate:
   - Connection registry: bytes per active SID
   - Expected max memory at peak concurrency

These artifacts will be provided when Phase 3A is complete, before Phase 3B begins.

### 2.7 Future: Adaptive Heartbeat Intervals

**Status:** Documented only — NOT implemented.

**Concept:** Instead of a fixed 60s interval, the client adjusts its heartbeat frequency based on observed activity:

| Activity Level | Heartbeat Interval | Rationale |
|----------------|-------------------|-----------|
| Active (typing, scrolling, clicking) | 30s | Faster Away detection for active users |
| Idle (visible but no input) | 60s | Default |
| Background tab | 120s | Reduce churn for backgrounded tabs |
| Page hidden / focused-away | No heartbeats | Tab not visible; server handles via `AWAY_TIMEOUT` |

**Implementation notes (when ready):**
- Server sends desired interval in the `connect` acknowledgment payload (e.g., `{ heartbeat_interval: 60 }`).
- Client uses `Page Visibility API` + idle detection to pick the tier.
- Heartbeat event payload includes a `tier` field so server can log/validate.
- `AWAY_TIMEOUT_SECONDS` should remain fixed at 180s regardless of tier (relates to wall-clock idle time, not missed-beat count).

### 2.8 Future: `Unknown` Startup State

**Status:** Documented only — NOT implemented.

**Concept:** After a server restart, all connected users were previously "known to be online" but the registry is empty. Adding an `Unknown` status would:

1. On first heartbeat after restart, emit `user_update { status: 'Unknown' }` for every user whose DB status was `Offline`.
2. Within one heartbeat cycle (≤60s), those users reconnect, trigger heartbeats, and transition to `Available`/`Busy`.
3. Users whose DB status was `Busy` (in a call when server crashed) remain `Busy` but with `reason='unknown'`.

**Benefits:**
- Clients would see a transient state rather than everyone appearing Offline then instantly flipping to Available.
- Prevents a "ghost offline" moment on reconnect.

**Deferred because:** The window is ≤60s and the UX improvement is marginal. Adding `Unknown` to the state machine adds test surface and client complexity for a very transient condition.

### 2.9 Presence Registry Singleton Lifecycle

```
          ┌──────────────────────────────────────────────────────────┐
          │                PresenceRegistry (singleton)               │
          │                    utils/presence.py                      │
          └──────────────────────────────────────────────────────────┘
                                    │
                                    │ Created at module import time
                                    │ (python import of utils.presence)
                                    ▼
          ┌──────────────────────────────────────────────────────────┐
          │                     INIT (empty)                         │
          │   _users = {}     _lock = threading.Lock()              │
          │   No data — no connection has been tracked yet.         │
          └──────────┬───────────────────────────────────────────────┘
                     │
                     │ get_or_create_user(username)
                     │ (called on socket connect)
                     ▼
          ┌──────────────────────────────────────────────────────────┐
          │                  RUNTIME (populated)                     │
          │   _users[username] → PresenceState { status, reason,    │
          │     last_heartbeat, connections: set(sid1, sid2, ...) } │
          │                                                         │
          │   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐│
          │   │  Available   │──▶│    Busy      │──▶│    Away      ││
          │   └──────────────┘   └──────────────┘   └──────────────┘│
          │         │               │                    │           │
          │         └───────────────┴────────────────────┘           │
          │                        │                                  │
          │                        ▼                                  │
          │               ┌──────────────┐                           │
          │               │   Offline    │  ← no connections (0 SIDs)│
          │               │  (DB sync)   │                           │
          │               └──────────────┘                           │
          └──────────────────────────────────────────────────────────┘
                     │
                     │ remove_connection(sid) → count=0
                     │ Registry still holds the PresenceState
                     │ (with status=Offline, last_heartbeat preserved)
                     ▼
          ┌──────────────────────────────────────────────────────────┐
          │                 STALE / ZOMBIE                           │
          │   status=Offline in both registry and DB.               │
          │   PresenceState kept in memory — redundant with DB.     │
          │   If user reconnects, get_or_create_user() finds the    │
          │   existing record and reuses it (overwriting state).    │
          └──────────────────────────────────────────────────────────┘
                     │
                     │ Server restart / shutdown
                     ▼
          ┌──────────────────────────────────────────────────────────┐
          │                 DESTROYED                                │
          │   Memory freed. All state lost — this is by design.     │
          │   DB holds only user.status and user.last_seen.         │
          └──────────────────────────────────────────────────────────┘

**Key lifecycle properties:**

| Property | Detail |
|----------|--------|
| Creation | Module-level `registry = PresenceRegistry()` — lazily created on first `from utils.presence import registry` |
| Thread safety | `threading.Lock()` protects all dict mutations; reads are lock-free for single-field access |
| Data loss on restart | By design — only DB columns (`status`, `last_seen`) survive. `presence_reason`, `last_heartbeat`, active SIDs are ephemeral |
| Reconnect after restart | DB `Offline` → Available (user just connected). DB `Busy` → preserved. `reason` = `None` |
| Stale entry cleanup | Entries with `status=Offline` and no connections are left in memory until the user reconnects. This is harmless (~400 bytes each) and avoids race conditions on rapid reconnect |
| Scalability | Single-process, single-thread-only via eventlet. The lock is a mutex, not a read-write lock — contention is negligible because all operations are O(1) dict lookups |
| Future clustering | This registry singleton is process-local. To scale across processes, presence would need Redis or similar. The presence abstraction layer is clean enough to swap the backing store without changing callers |
|

---

## 3. Changes by File

### 3.1 NEW — `utils/presence.py`

```python
"""Runtime presence registry — in-memory, no database writes for presence metadata."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PresenceState:
    """Runtime presence metadata for a single user.

    This data is transient. It does NOT survive server restarts.
    Persistent data (status, last_seen) lives in the User model (DB).
    """
    status: str = 'Offline'
    reason: Optional[str] = None
    last_heartbeat: Optional[datetime] = None
    connections: set = field(default_factory=set)


class PresenceRegistry:
    """In-memory registry for runtime presence state.

    Thread-safe. Holds status, reason, heartbeat timing, and SIDs.
    The User model in the database holds the persistent source of truth
    for status and last_seen; the registry adds transient metadata and
    fast in-memory lookups.
    """

    def __init__(self):
        self._users: dict[str, PresenceState] = {}
        self._lock = threading.Lock()

    # ── Connection tracking ──────────────────────────────

    def add_connection(self, username: str, sid: str) -> int:
        with self._lock:
            state = self._users.setdefault(username, PresenceState())
            state.connections.add(sid)
            return len(state.connections)

    def remove_connection(self, username: str, sid: str) -> int:
        with self._lock:
            state = self._users.get(username)
            if not state:
                return 0
            state.connections.discard(sid)
            count = len(state.connections)
            if count == 0:
                del self._users[username]
            return count

    def connection_count(self, username: str) -> int:
        with self._lock:
            state = self._users.get(username)
            return len(state.connections) if state else 0

    @property
    def total_connections(self) -> int:
        with self._lock:
            return sum(len(s.connections) for s in self._users.values())

    # ── Online / offline queries ─────────────────────────

    def is_online(self, username: str) -> bool:
        with self._lock:
            state = self._users.get(username)
            return state is not None and bool(state.connections)

    def online_users(self) -> set[str]:
        with self._lock:
            return {u for u, s in self._users.items() if s.connections}

    # ── Status management ────────────────────────────────

    def get_status(self, username: str) -> Optional[str]:
        with self._lock:
            state = self._users.get(username)
            return state.status if state else None

    def set_status(self, username: str, status: str,
                   reason: Optional[str] = None) -> None:
        with self._lock:
            state = self._users.setdefault(username, PresenceState())
            state.status = status
            if reason is not None:
                state.reason = reason

    def get_reason(self, username: str) -> Optional[str]:
        with self._lock:
            state = self._users.get(username)
            return state.reason if state else None

    # ── Heartbeat ────────────────────────────────────────

    def update_heartbeat(self, username: str) -> None:
        with self._lock:
            state = self._users.setdefault(username, PresenceState())
            state.last_heartbeat = datetime.utcnow()

    def get_last_heartbeat(self, username: str) -> Optional[datetime]:
        with self._lock:
            state = self._users.get(username)
            return state.last_heartbeat if state else None

    # ── Cleanup ──────────────────────────────────────────

    def disconnect_all(self) -> None:
        with self._lock:
            self._users.clear()

    def state_snapshot(self) -> dict:
        """Return a snapshot of all presence state (for diagnostics)."""
        with self._lock:
            return {
                u: {
                    'status': s.status,
                    'reason': s.reason,
                    'last_heartbeat': s.last_heartbeat.isoformat()
                    if s.last_heartbeat else None,
                    'connections': len(s.connections),
                }
                for u, s in self._users.items()
            }


# Module-level singleton
registry = PresenceRegistry()
```

### 3.2 Modified — `models/models.py`

**No changes.** The `presence_reason` column is intentionally NOT added to the User model. Presence metadata (reason, heartbeat timing, connection count) is runtime state stored in `PresenceRegistry` (§3.1) — not in the database.

### 3.3 Modified — `utils/security/constants.py`

Add presence section:

```python
# ──────────────────────────────────────────────
# Presence / Status
# ──────────────────────────────────────────────

VALID_STATUS_VALUES: frozenset = frozenset({
    'Available',
    'Busy',
    'Away',
    'Invisible',   # RESERVED — no behavior implemented yet
    'Offline',
})

# Client sends heartbeat every N seconds.
HEARTBEAT_INTERVAL_SECONDS: int = 60

# User is set to Away after N seconds without a heartbeat.
AWAY_TIMEOUT_SECONDS: int = 60

# User is considered fully offline after N seconds without a heartbeat
# (for broadcast filtering of stale connections).
PRESENCE_TIMEOUT_SECONDS: int = 120

# Debounce window for presence broadcasts (milliseconds).
PRESENCE_DEBOUNCE_MS: int = 500

# Interval for the background presence check task (seconds).
PRESENCE_CHECK_INTERVAL_SECONDS: int = 30
```

Also update `SOCKET_IO_RATE_LIMITS` to include `'heartbeat'`:

```python
SOCKET_IO_RATE_LIMITS: dict = {
    # ... existing ...
    'heartbeat': 2,  # Max 2 heartbeats/second (60s interval = well under limit)
}
```

### 3.4 Modified — `sockets/events.py`

#### Imports
```python
from utils.presence import registry
from utils.security.constants import (
    AWAY_TIMEOUT_SECONDS,
    PRESENCE_DEBOUNCE_MS,
)
```

#### Helper: load DB status into registry

```python
def _ensure_registry_state(username: str) -> str:
    """Load user's persisted status into registry if not already present.

    Returns the resolved status to use.
    """
    existing = registry.get_status(username)
    if existing is not None:
        return existing  # Already tracked in registry
    user = User.query.filter_by(username=username).first()
    if not user:
        return 'Offline'
    db_status = user.status
    if db_status == 'Offline':
        db_status = 'Available'  # Connecting user is no longer offline
    registry.set_status(username, db_status, reason='active')
    return db_status
```

#### Connect handler
```python
@socketio.on('connect')
def handle_connect():
    username = session.get('username')
    if not username:
        return False
    prev_online = registry.is_online(username)
    count = registry.add_connection(username, request.sid)
    registry.update_heartbeat(username)
    user = User.query.filter_by(username=username).first()
    if not user:
        return False
    if count == 1 and not prev_online:
        # First connection — set Available (was Offline)
        registry.set_status(username, 'Available', reason='active')
        user.status = 'Available'
        user.last_seen = datetime.utcnow()
        db.session.commit()
        debounced_broadcast()
    else:
        # Additional tab — just refresh last_seen
        user.last_seen = datetime.utcnow()
        db.session.commit()
    emit('user_list', build_user_list(username))
```

#### Disconnect handler
```python
@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username')
    if not username:
        return
    count = registry.remove_connection(username, request.sid)
    if count == 0:
        # Last connection gone
        registry.set_status(username, 'Offline', reason='disconnected')
        user = User.query.filter_by(username=username).first()
        if user:
            user.status = 'Offline'
            user.last_seen = datetime.utcnow()
            db.session.commit()
            debounced_broadcast()
```

#### Heartbeat handler
```python
@socketio.on('heartbeat')
def handle_heartbeat(data):
    username = session.get('username')
    if not username:
        return
    registry.update_heartbeat(username)
    user = User.query.filter_by(username=username).first()
    if not user:
        return
    resumed = False
    reg_status = registry.get_status(username)
    if reg_status == 'Away':
        registry.set_status(username, 'Available', reason='active')
        user.status = 'Available'
        resumed = True
    user.last_seen = datetime.utcnow()
    db.session.commit()
    if resumed:
        debounced_broadcast()
```

#### Away detection (background task)
```python
def check_away_users():
    """Mark users as Away if no heartbeat for AWAY_TIMEOUT_SECONDS."""
    threshold = datetime.utcnow() - timedelta(seconds=AWAY_TIMEOUT_SECONDS)
    changed = []
    for username in registry.online_users():
        last_hb = registry.get_last_heartbeat(username)
        if last_hb is None or last_hb > threshold:
            continue
        reg_status = registry.get_status(username)
        if reg_status in ('Available', 'Busy'):
            registry.set_status(username, 'Away', reason='idle_timeout')
            user = User.query.filter_by(username=username).first()
            if user:
                user.status = 'Away'
                changed.append(user)
    if changed:
        db.session.commit()
        debounced_broadcast()
```

#### Debounced broadcast
```python
_last_broadcast: float = 0

def debounced_broadcast():
    global _last_broadcast
    now = time.time() * 1000
    if now - _last_broadcast < PRESENCE_DEBOUNCE_MS:
        return
    _last_broadcast = now
    _send_user_updates()

def _send_user_updates():
    """Emit user_update for all users.

    TODO (Phase 3C): Filter Invisible users from other users' presence views.
    """
    online = registry.online_users()
    all_users = User.query.all()
    for user in all_users:
        data = {
            "name": user.username,
            "status": registry.get_status(user.username) or user.status,
            "last_seen": user.last_seen.isoformat() + "Z" if user.last_seen else None,
            "is_online": user.username in online,
        }
        socketio.emit('user_update', data)
```

#### Auto-busy on WebRTC call
```python
@socketio.on('call_start')
def handle_call_start(data):
    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    if not user:
        return
    reg_status = registry.get_status(username)
    if reg_status and reg_status not in ('Busy', 'Away', 'Offline'):
        registry.set_status(username, 'Busy', reason='in_call')
        user.status = 'Busy'
        db.session.commit()
        debounced_broadcast()

@socketio.on('call_end')
def handle_call_end(data):
    username = session.get('username')
    user = User.query.filter_by(username=username).first()
    if not user:
        return
    reg_status = registry.get_status(username)
    if reg_status == 'Busy':
        reg_reason = registry.get_reason(username)
        if reg_reason == 'in_call':
            # Restore previous status (only if Busy was set by call_start)
            prev_status = 'Available'
            registry.set_status(username, prev_status, reason='active')
            user.status = prev_status
            db.session.commit()
            debounced_broadcast()
```

#### Remove `broadcast_user_list()` from message/read handlers

In `send_message`, `message_read`, `mark_all_read` — remove calls to `broadcast_user_list()`. Message delivery is handled by existing `new_message` / `message_read` events. Presence-only changes are handled by `debounced_broadcast()`.

#### Rate limit registration

Add `'heartbeat'` to the rate limit dict (see §3.3) and register it in the rate limiter initialization if not already dynamic.

### 3.5 Modified — `app.py`

**Remove** the startup loop that resets all users to `Offline`:

```python
# REMOVED (lines 176-178):
# with app.app_context():
#     User.query.update({User.status: 'Offline'})
#     db.session.commit()
#     logger.info("Successfully reset all user statuses to Offline on startup.")
```

**Add** background scheduler for `check_away_users()`:

```python
from utils.security.constants import PRESENCE_CHECK_INTERVAL_SECONDS

def _start_presence_checker(app):
    """Start background thread for presence timeout detection."""
    import threading
    def _check():
        with app.app_context():
            from sockets.events import check_away_users
            while True:
                import time
                time.sleep(PRESENCE_CHECK_INTERVAL_SECONDS)
                try:
                    check_away_users()
                except Exception:
                    app.logger.exception("Presence check failed")
    t = threading.Thread(target=_check, daemon=True, name="presence-checker")
    t.start()
```

Call `_start_presence_checker(app)` before `socketio.run()` or during app factory setup.

### 3.6 NEW — `tests/test_presence.py`

| Test | Description |
|------|-------------|
| Test | Description |
|------|-------------|
| `test_registry_add_connection` | Add SID → count=1, add same user → count=2 |
| `test_registry_remove_connection` | Remove → count=1, remove last → count=0 (user evicted) |
| `test_registry_is_online` | User with active SID is online; removed user is offline |
| `test_registry_online_users` | Returns correct set of users with count > 0 |
| `test_registry_disconnect_all` | Clears all entries |
| `test_registry_thread_safety` | 20 concurrent threads add/remove |
| `test_registry_total_connections` | Property sums all SIDs |
| `test_registry_set_get_status` | set_status / get_status round-trip |
| `test_registry_set_get_reason` | set_status(reason=...) / get_reason round-trip |
| `test_registry_update_heartbeat` | update_heartbeat / get_last_heartbeat round-trip |
| `test_connect_first_tab` | First connect sets status Available, broadcasts |
| `test_connect_second_tab` | Second connect does NOT change status, no broadcast |
| `test_disconnect_last_tab` | Last tab close sets Offline, reason='disconnected', broadcasts |
| `test_disconnect_mid_tab` | Middle tab close does NOT change status |
| `test_heartbeat_updates_last_seen` | Heartbeat refreshes DB `last_seen` |
| `test_heartbeat_resumes_away` | Heartbeat transitions Away → Available, reason='active' |
| `test_away_detection` | User without heartbeat for >AWAY_TIMEOUT_SECONDS set to Away, reason='idle_timeout' |
| `test_away_detection_skips_recent` | User with recent heartbeat is NOT set to Away |
| `test_away_detection_skips_offline` | check_away_users skips disconnected users |
| `test_debounced_broadcast_skip` | Second call within PRESENCE_DEBOUNCE_MS is skipped |
| `test_debounced_broadcast_fires` | Call after debounce delay fires |
| `test_status_expansion` | 'Away' and 'Invisible' are in VALID_STATUS_VALUES |
| `test_invisible_reserved` | 'Invisible' exists with no runtime behavior |
| `test_presence_reason_runtime_only` | Reason is in registry, NOT in DB |
| `test_call_start_sets_busy` | `call_start` sets Busy, reason='in_call' |
| `test_call_end_restores_status` | `call_end` restores previous status |
| `test_no_startup_reset` | App startup does not alter user statuses |
| `test_heartbeat_rate_limit` | 'heartbeat' has an entry in SOCKET_IO_RATE_LIMITS |

---

## 4. Implementation Order

| Step | Description | Files |
|------|-------------|-------|
| 1 | Add `presence_reason` column to User model | `models/models.py` |
| 2 | Add presence timing constants to constants.py | `utils/security/constants.py` |
| 3 | Add `Invisible` to `VALID_STATUS_VALUES` | `utils/security/constants.py` |
| 4 | Create `utils/presence.py` with `ConnectionRegistry` | NEW |
| 5 | Update connect handler: registry, multi-tab, reason | `sockets/events.py` |
| 6 | Update disconnect handler: last-tab-only Offline, reason | `sockets/events.py` |
| 7 | Add heartbeat handler | `sockets/events.py` |
| 8 | Add `check_away_users()` scheduled task | `sockets/events.py` |
| 9 | Add debounced broadcast + `_send_user_updates()` | `sockets/events.py` |
| 10 | Remove `broadcast_user_list()` from message/read handlers | `sockets/events.py` |
| 11 | Add auto-busy `call_start`/`call_end` handlers | `sockets/events.py` |
| 12 | Remove startup status reset from app.py | `app.py` |
| 13 | Add background presence checker to app startup | `app.py` |
| 14 | Write `tests/test_presence.py` — all tests from §3.6 | NEW |
| 15 | Run full regression + produce artifacts report | Verify |

---

## 5. Risk Assessment

| Risk | Mitigation |
|------|------------|
| Connection registry uses memory — lost on server restart | Database status is the source of truth; registry rebuilds naturally as clients reconnect. Worst case: all users appear Offline until heartbeat resumes (≤60s). |
| Debounce misses a rare status change within 500ms window | Acceptable — presence at 500ms granularity is imperceptible to users. The last status within the window always fires. |
| `_previous_status` stored in-memory, lost on crash | Acceptable — the WebRTC call would also be lost on server restart. User's DB status persists. |
| Thread safety on registry | `threading.Lock` guards all mutations. Lock held briefly (dict ops only). |
| Heartbeat adds periodic DB writes | Single-row update per user, no joins, no indexes to update on `last_seen`/`presence_reason`. At 100 concurrent users: ~1.7 writes/second total. |
| Background thread for `check_away_users()` introduces concurrency | All DB work runs inside `app.app_context()`. Thread is daemon — safe for shutdown. |
| Adding `presence_reason` column requires migration | New nullable column — no backfill needed. Existing rows get `NULL`. |

---

## 6. Verification & Artifacts

After implementation:

```bash
python -m pytest tests/ -v --tb=short
```

Expected: all existing (191) tests pass + all new presence tests pass.

### Artifacts to produce:

1. **Presence lifecycle diagram** — ASCII state machine (see §2.4)
2. **Backend regression report** — Full test output summary
3. **Performance impact estimate:**
   - Queries per `send_message`: from N+2 queries down to 1 query (no `broadcast_user_list()` call)
   - Broadcasts per connect: from N+1 emits down to 1 emit (`user_update` instead of per-user `user_list`)
   - DB writes from heartbeats: `heartbeats_per_second = online_users / 60`
4. **Memory impact:**
   - Per active SID: ~200 bytes (dict entry + set entry + string)
   - At 100 users × 2 tabs = 200 SIDs → ~40 KB (negligible)
   - At 1000 users × 3 tabs = 3000 SIDs → ~600 KB (negligible)

---

## Appendix: Event Model Review

### Dedicated Events Considered

If dedicated presence events were used, the socket contract would be:

| Event | Direction | Payload | When |
|-------|-----------|---------|------|
| `presence_online` | Server → All | `{"name", "last_seen"}` | User connects or resumes from Away |
| `presence_away` | Server → All | `{"name"}` | User times out to Away |
| `presence_offline` | Server → All | `{"name", "last_seen"}` | User disconnects last tab |
| `presence_busy` | Server → All | `{"name"}` | User starts a call |
| `presence_available` | Server → All | `{"name"}` | User ends a call / manually sets |

### Why `user_update` Wins

| Factor | Dedicated Events | `user_update` |
|--------|-----------------|---------------|
| Client code | 5 handlers, each ~5 lines = 25 lines total | 1 handler, ~15 lines with switch |
| Adding Invisible (future) | New event: `presence_invisible` | No change — just new status value |
| Adding reason field (future) | 5 payloads to update | 1 payload to update |
| Testing | 5 event types to test | 1 event type to test |
| Ordering guarantees | If `presence_online` arrives after `presence_offline`, client shows wrong state | Single event stream preserves order naturally |

**Decision: `user_update` is the single presence event.** This reduces complexity, improves extensibility, and simplifies testing.
