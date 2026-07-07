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
    previous_status: Optional[str] = None


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

    def save_previous_status(self, username: str) -> Optional[str]:
        with self._lock:
            state = self._users.get(username)
            if state:
                state.previous_status = state.status
                return state.status
            return None

    def pop_previous_status(self, username: str) -> Optional[str]:
        with self._lock:
            state = self._users.get(username)
            if state and state.previous_status:
                prev = state.previous_status
                state.previous_status = None
                return prev
            return None

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

    def rename_user(self, old_username: str, new_username: str) -> None:
        """Rename a user in the registry, preserving their presence state.

        Must be called AFTER the DB transaction commits.
        No-op if the old username is not tracked.
        """
        with self._lock:
            state = self._users.pop(old_username, None)
            if state is not None:
                self._users[new_username] = state

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


registry = PresenceRegistry()
