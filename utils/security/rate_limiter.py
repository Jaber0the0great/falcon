"""In-memory sliding-window rate limiter and decorator for Flask routes.

Thread-safe. Uses a dict of lists keyed by (client IP, user ID, etc.)
with automatic expiry of stale entries.
"""

import time
import threading
from functools import wraps

from flask import request, jsonify, session, current_app


class InMemoryRateLimiter:
    """Sliding-window rate limiter backed by an in-memory dict.

    Each key stores a sorted list of event timestamps within the
    current window.  Expired timestamps are pruned lazily on every
    ``check()`` call.
    """

    def __init__(self):
        self._store: dict = {}
        self._lock = threading.Lock()

    def check(self, key: str, max_calls: int, window_seconds: int) -> bool:
        """Return *True* if the request is allowed, *False* if rate-limited."""
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._store.get(key, [])
            # Prune expired entries
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= max_calls:
                self._store[key] = timestamps
                return False

            timestamps.append(now)
            self._store[key] = timestamps
            return True

    def clear(self):
        """Remove **all** rate-limit state (useful in tests)."""
        with self._lock:
            self._store.clear()


# ── Global singleton ────────────────────────────────────────────────────────

_limiter = InMemoryRateLimiter()


# ── Key factories ───────────────────────────────────────────────────────────

def ip_key(*args, **kwargs):
    """Key by client IP address."""
    return f"ip:{request.remote_addr or 'unknown'}"


def user_key(*args, **kwargs):
    """Key by authenticated user ID, falling back to IP."""
    uid = session.get('user_id')
    if uid is not None:
        return f"user:{uid}"
    return f"ip:{request.remote_addr or 'unknown'}"


def admin_key(*args, **kwargs):
    """Key by admin user ID, falling back to IP."""
    if session.get('admin_logged_in'):
        return f"admin:{session.get('user_id', 'unknown')}"
    return f"ip:{request.remote_addr or 'unknown'}"


# ── Unique-per-decorator scope counter ─────────────────────────────────────

_decorator_counter = 0


def _next_scope_id() -> int:
    """Return a monotonically increasing integer unique to each decorator call."""
    global _decorator_counter
    _decorator_counter += 1
    return _decorator_counter


# ── Decorator ───────────────────────────────────────────────────────────────

def rate_limit(max_calls: int, window_seconds: int = 60, key_func=ip_key):
    """Decorator that applies a sliding-window rate limit to a Flask view.

    Each ``@rate_limit()`` invocation gets its **own** isolated counter slot
    so that limits for different endpoints (or categories) do not collide
    even when they share the same *key_func* value.

    Parameters
    ----------
    max_calls:
        Maximum number of requests allowed within the time window.
    window_seconds:
        Duration of the sliding window in seconds (default 60).
    key_func:
        Callable that returns the rate-limit key.  Receives the same
        positional and keyword arguments as the view function.  Built-in
        factories: :func:`ip_key`, :func:`user_key`, :func:`admin_key`.
    """
    scope_id = _next_scope_id()

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if current_app.config.get('TESTING'):
                return f(*args, **kwargs)
            base_key = key_func(*args, **kwargs)
            key = f"{base_key}:rl{scope_id}"
            if not _limiter.check(key, max_calls, window_seconds):
                return jsonify(
                    {
                        "success": False,
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Rate limit exceeded. Please slow down."
                        },
                    }
                ), 429
            return f(*args, **kwargs)
        return wrapper
    return decorator
