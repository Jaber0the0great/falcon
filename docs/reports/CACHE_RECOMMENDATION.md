# Cache Recommendation

## Context

After P1+P2, `broadcast_user_list()` issues only **4 queries** regardless of user count (2 User queries + 1 unread batch + 1 last-msg batch). The benchmark shows:

| Scale | Time | Bottleneck |
|-------|------|------------|
| 10 users / 10 online | 3.5 ms | Negligible |
| 100 users / 70 online | 51 ms | Python loop + Socket.IO emit |
| 200 users / 140 online | 236 ms | Python loop + Socket.IO emit |
| 1000 users / 500 online (est.) | ~2–3 s | Python loop + Socket.IO emit |

The DB queries are no longer the bottleneck. The remaining cost is:
1. **Python loop**: Building 27,000+ user entries (140 recipients × 199 other users = 27,860 iterations at 200 users)
2. **Socket.IO emit**: Serializing and sending 140 separate personalized messages

## Is Caching Justified?

**Not for query reduction.** Queries are already at a constant minimum (4). Caching would not reduce DB load further.

**Possibly for CPU/emit reduction**, but the benefit is marginal:

| Argument | Detail |
|----------|--------|
| Call frequency | `broadcast_user_list()` fires on every connect, disconnect, message send, message read, mark-all-read, and status update. On a busy chat: ~5-20 calls/minute. |
| Cache hit potential | If no relevant data changed between calls (no new messages, no status changes, no read receipts), a cached result would be identical. But these events are what *trigger* the call, so a cache would rarely hit. |
| Invalidation complexity | To invalidate correctly you must track: which user's unread count changed, which conversation's last message changed, which user's status changed. This is equivalent to the work of computing the result. |

**Recommendation: Do NOT implement a full cache.**

Instead, apply the following optimizations (in priority order):

### 1. Differential Updates (Preferred Over Caching)

Rather than re-emitting the full `user_list` to every online user, emit **incremental deltas**:

- When user A sends a message to user B:
  - Only re-emit `user_list` to users A and B (their unread counts + last-message changed)
  - Everyone else's view is unchanged

This changes the cost from O(O × N) to O(1 or 2) per event.

**Trade-off**: Requires changes to Socket.IO event flow. Increases client complexity. Deferred to a future architecture phase.

### 2. Reduce Emit Frequency (Debounce)

For events that always batch together (e.g., user connects + receives 10 pending messages + marks 5 as read), `broadcast_user_list()` is called multiple times in rapid succession. A **debounce** (e.g., 100ms window) coalesces multiple calls into one.

```python
_broadcast_pending = False

def broadcast_user_list():
    if _broadcast_pending:
        return
    _broadcast_pending = True
    socketio.start_background_task(_delayed_broadcast)

def _delayed_broadcast():
    time.sleep(0.1)  # coalesce window
    _broadcast_pending = False
    # ... actual computation ...
```

**Trade-off**: Adds 100ms latency to user list updates. Acceptable for non-critical presence data.

### 3. TTL-based Read Cache (Fallback)

If differential updates prove too complex, a simple TTL cache (e.g., 500ms) skips recomputation when `broadcast_user_list()` is called more than once within the window:

```python
from functools import lru_cache
import time

_last_broadcast_time = 0
_cached_result = None

def broadcast_user_list():
    now = time.time()
    if now - _last_broadcast_time < 0.5:
        return  # too soon, skip
    _last_broadcast_time = now
    # ... actual computation ...
```

**Trade-off**: Presence data may be up to 500ms stale. Acceptable. Simple to implement.

## Conclusion

**No cache layer is needed at this stage.** The P1+P2 optimizations already reduced query count by 99.9%+ and execution time by 60–243×. At 200 users, a single invocation takes ~236ms — dominated by the unavoidable Socket.IO emit cost.

If user count grows beyond 1,000, pursue **differential updates** (Option 1) instead of caching. This eliminates the O(N²) emit cost rather than hiding it behind stale data.
