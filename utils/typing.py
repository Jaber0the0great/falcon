"""Runtime typing state — in-memory, no database writes."""

import threading
from typing import Optional


class TypingTracker:
    """Tracks who is typing in which conversation.

    Thread-safe. Keys are ``private:<username>`` or ``group:<group_name>``.
    On disconnect, ``clear_user()`` removes the user from all conversations
    to prevent stuck typing indicators.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._typing: dict[str, set[str]] = {}

    def _normalise(self, username: str, target: str,
                   type_: str) -> tuple[str, str]:
        """Return (conversation_key, room_name)."""
        if type_ == 'group':
            return f"group:{target}", target
        # Private: the conversation key is the pair, sorted lexicographically
        pair = tuple(sorted((username, target)))
        return f"private:{pair[0]}:{pair[1]}", target

    def start(self, username: str, target: str,
              type_: str = 'private') -> Optional[str]:
        """Mark user as typing in a conversation. Returns the room name
        that should receive the ``user_typing`` event, or None if already
        typing."""
        conv, room = self._normalise(username, target, type_)
        with self._lock:
            if conv not in self._typing:
                self._typing[conv] = set()
            if username in self._typing[conv]:
                return None  # already known — skip duplicate broadcast
            self._typing[conv].add(username)
            return room

    def stop(self, username: str, target: str,
             type_: str = 'private') -> Optional[str]:
        """Mark user as no longer typing. Returns the room name that
        should receive the ``user_typing_stop`` event, or None if the
        user wasn't typing."""
        conv, room = self._normalise(username, target, type_)
        with self._lock:
            s = self._typing.get(conv)
            if not s or username not in s:
                return None
            s.discard(username)
            if not s:
                del self._typing[conv]
            return room

    def typing_users(self, username: str, target: str,
                     type_: str = 'private') -> set[str]:
        """Return set of usernames currently typing in the conversation
        (excluding the given user)."""
        conv, _ = self._normalise(username, target, type_)
        with self._lock:
            s = self._typing.get(conv)
            if not s:
                return set()
            return {u for u in s if u != username}

    def clear_user(self, username: str) -> list[tuple[str, str]]:
        """Remove user from all conversations. Returns list of
        (room_name, type_) tuples to notify."""
        notified: list[tuple[str, str]] = []
        with self._lock:
            for conv, users in list(self._typing.items()):
                if username in users:
                    users.discard(username)
                    if not users:
                        del self._typing[conv]
                    # Determine room from conversation key
                    if conv.startswith("private:"):
                        parts = conv.split(":")
                        # parts = ['private', user_a, user_b]
                        other = parts[1] if parts[1] != username else parts[2]
                        notified.append((other, 'private'))
                    elif conv.startswith("group:"):
                        notified.append((conv[6:], 'group'))
        return notified


typing_tracker = TypingTracker()
