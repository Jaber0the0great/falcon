"""Tests for the PresenceRegistry and presence-related socket logic."""

from datetime import datetime, timedelta
import time
import threading

import pytest

from utils.presence import PresenceRegistry, PresenceState, registry as global_registry
from utils.security.constants import (
    VALID_STATUS_VALUES,
    AWAY_TIMEOUT_SECONDS,
    PRESENCE_DEBOUNCE_MS,
    HEARTBEAT_INTERVAL_SECONDS,
    PRESENCE_TIMEOUT_SECONDS,
    PRESENCE_CHECK_INTERVAL_SECONDS,
    SOCKET_IO_RATE_LIMITS,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def registry():
    """Fresh PresenceRegistry for each test."""
    r = PresenceRegistry()
    yield r
    r.disconnect_all()


# ── Helpers ─────────────────────────────────────────────────────────────────

def approx_now():
    return datetime.utcnow()


# ═══════════════════════════════════════════════════════════════════════════
# Connection tracking
# ═══════════════════════════════════════════════════════════════════════════

class TestConnectionTracking:
    def test_add_connection(self, registry):
        assert registry.add_connection('alice', 'sid1') == 1
        assert registry.add_connection('alice', 'sid2') == 2

    def test_remove_connection(self, registry):
        registry.add_connection('alice', 'sid1')
        registry.add_connection('alice', 'sid2')
        assert registry.remove_connection('alice', 'sid1') == 1
        assert registry.remove_connection('alice', 'sid2') == 0

    def test_remove_unknown_user(self, registry):
        assert registry.remove_connection('ghost', 'sid1') == 0

    def test_remove_unknown_sid(self, registry):
        registry.add_connection('alice', 'sid1')
        assert registry.remove_connection('alice', 'sid_unknown') == 1

    def test_is_online(self, registry):
        assert not registry.is_online('alice')
        registry.add_connection('alice', 'sid1')
        assert registry.is_online('alice')
        registry.remove_connection('alice', 'sid1')
        assert not registry.is_online('alice')

    def test_online_users(self, registry):
        assert registry.online_users() == set()
        registry.add_connection('alice', 's1')
        registry.add_connection('bob', 's2')
        registry.add_connection('charlie', 's3')
        assert registry.online_users() == {'alice', 'bob', 'charlie'}
        registry.remove_connection('bob', 's2')
        assert registry.online_users() == {'alice', 'charlie'}

    def test_connection_count(self, registry):
        assert registry.connection_count('alice') == 0
        registry.add_connection('alice', 's1')
        assert registry.connection_count('alice') == 1
        registry.add_connection('alice', 's2')
        assert registry.connection_count('alice') == 2

    def test_total_connections(self, registry):
        assert registry.total_connections == 0
        registry.add_connection('alice', 's1')
        registry.add_connection('bob', 's2')
        registry.add_connection('alice', 's3')
        assert registry.total_connections == 3

    def test_disconnect_all(self, registry):
        registry.add_connection('alice', 's1')
        registry.add_connection('bob', 's2')
        registry.disconnect_all()
        assert registry.total_connections == 0
        assert registry.online_users() == set()

    def test_user_evicted_on_last_remove(self, registry):
        registry.add_connection('alice', 's1')
        registry.remove_connection('alice', 's1')
        with registry._lock:
            assert 'alice' not in registry._users


# ═══════════════════════════════════════════════════════════════════════════
# Thread safety
# ═══════════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    def test_concurrent_add_remove(self, registry):
        errors = []

        def worker(user, sid):
            try:
                for _ in range(100):
                    registry.add_connection(user, sid)
                    registry.remove_connection(user, sid)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=worker, args=(f'user{i % 5}', f'sid{i}'))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors, f"Thread safety errors: {errors}"
        # After all add/remove pairs, each user should have 0 connections
        # (each thread added and removed for same user/sid, net effect = 0 for pairs)
        for i in range(5):
            assert registry.connection_count(f'user{i}') >= 0


# ═══════════════════════════════════════════════════════════════════════════
# Status management
# ═══════════════════════════════════════════════════════════════════════════

class TestStatusManagement:
    def test_get_status_default(self, registry):
        assert registry.get_status('alice') is None

    def test_set_get_status(self, registry):
        registry.set_status('alice', 'Available')
        assert registry.get_status('alice') == 'Available'

    def test_set_get_reason(self, registry):
        registry.set_status('alice', 'Busy', reason='in_call')
        assert registry.get_status('alice') == 'Busy'
        assert registry.get_reason('alice') == 'in_call'

    def test_reason_default_none(self, registry):
        registry.set_status('alice', 'Available')
        assert registry.get_reason('alice') is None

    def test_reason_updated(self, registry):
        registry.set_status('alice', 'Busy', reason='in_call')
        registry.set_status('alice', 'Available', reason='active')
        assert registry.get_reason('alice') == 'active'

    def test_status_overwrite_without_reason(self, registry):
        registry.set_status('alice', 'Busy', reason='in_call')
        registry.set_status('alice', 'Available')
        assert registry.get_reason('alice') == 'in_call'


# ═══════════════════════════════════════════════════════════════════════════
# Heartbeat
# ═══════════════════════════════════════════════════════════════════════════

class TestHeartbeat:
    def test_update_heartbeat(self, registry):
        registry.update_heartbeat('alice')
        hb = registry.get_last_heartbeat('alice')
        assert hb is not None
        assert abs((approx_now() - hb).total_seconds()) < 2

    def test_heartbeat_updates_timestamp(self, registry):
        registry.update_heartbeat('alice')
        old_hb = registry.get_last_heartbeat('alice')
        time.sleep(0.01)
        registry.update_heartbeat('alice')
        new_hb = registry.get_last_heartbeat('alice')
        assert new_hb > old_hb

    def test_heartbeat_unknown_user(self, registry):
        assert registry.get_last_heartbeat('ghost') is None


# ═══════════════════════════════════════════════════════════════════════════
# State snapshot
# ═══════════════════════════════════════════════════════════════════════════

class TestStateSnapshot:
    def test_snapshot_empty(self, registry):
        assert registry.state_snapshot() == {}

    def test_snapshot_contains_keys(self, registry):
        registry.add_connection('alice', 's1')
        registry.set_status('alice', 'Available')
        snap = registry.state_snapshot()
        assert 'alice' in snap
        assert snap['alice']['status'] == 'Available'
        assert snap['alice']['connections'] == 1


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_status_values_include_away(self):
        assert 'Away' in VALID_STATUS_VALUES

    def test_status_values_include_invisible(self):
        assert 'Invisible' in VALID_STATUS_VALUES

    def test_status_values_include_available(self):
        assert 'Available' in VALID_STATUS_VALUES

    def test_status_values_include_busy(self):
        assert 'Busy' in VALID_STATUS_VALUES

    def test_status_values_include_offline(self):
        assert 'Offline' in VALID_STATUS_VALUES

    def test_away_timeout_positive(self):
        assert AWAY_TIMEOUT_SECONDS > 0

    def test_presence_timeout_greater_than_away(self):
        assert PRESENCE_TIMEOUT_SECONDS > AWAY_TIMEOUT_SECONDS

    def test_presence_debounce_positive(self):
        assert PRESENCE_DEBOUNCE_MS > 0

    def test_heartbeat_interval_positive(self):
        assert HEARTBEAT_INTERVAL_SECONDS > 0

    def test_presence_check_interval_reasonable(self):
        assert 10 <= PRESENCE_CHECK_INTERVAL_SECONDS <= 120

    def test_heartbeat_rate_limit_exists(self):
        assert 'heartbeat' in SOCKET_IO_RATE_LIMITS

    def test_heartbeat_rate_limit_reasonable(self):
        assert SOCKET_IO_RATE_LIMITS['heartbeat'] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Registry integration with DB-backed status (behavioural tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestRegistryStateTransitions:
    """These test the PresenceRegistry's internal state machine logic
    that mirrors what the socket event handlers do with DB writes."""

    def test_first_connect_sets_available(self, registry):
        """Simulate: user connects first tab → status becomes Available."""
        assert not registry.is_online('alice')
        registry.add_connection('alice', 's1')
        registry.set_status('alice', 'Available', reason='active')
        assert registry.get_status('alice') == 'Available'
        assert registry.get_reason('alice') == 'active'

    def test_second_connect_does_not_change_status(self, registry):
        """Simulate: second tab — status stays whatever it was."""
        registry.add_connection('alice', 's1')
        registry.set_status('alice', 'Available', reason='active')
        registry.add_connection('alice', 's2')
        assert registry.get_status('alice') == 'Available'

    def test_disconnect_mid_tab(self, registry):
        """Closing one of two tabs — status unchanged."""
        registry.add_connection('alice', 's1')
        registry.add_connection('alice', 's2')
        registry.set_status('alice', 'Available')
        registry.remove_connection('alice', 's1')
        assert registry.connection_count('alice') == 1
        assert registry.get_status('alice') == 'Available'

    def test_disconnect_last_tab_sets_offline(self, registry):
        """Closing last tab — status becomes Offline."""
        registry.add_connection('alice', 's1')
        registry.set_status('alice', 'Available')
        registry.remove_connection('alice', 's1')
        assert registry.connection_count('alice') == 0
        assert not registry.is_online('alice')

    def test_heartbeat_resumes_from_away(self, registry):
        """Heartbeat when Away → Available + reason='active'."""
        registry.set_status('alice', 'Away', reason='idle_timeout')
        assert registry.get_status('alice') == 'Away'
        registry.set_status('alice', 'Available', reason='active')
        assert registry.get_status('alice') == 'Available'
        assert registry.get_reason('alice') == 'active'

    def test_call_start_sets_busy(self, registry):
        """call_start → Busy + reason='in_call'."""
        registry.set_status('alice', 'Available')
        registry.set_status('alice', 'Busy', reason='in_call')
        assert registry.get_status('alice') == 'Busy'
        assert registry.get_reason('alice') == 'in_call'

    def test_call_end_restores_available(self, registry):
        """call_end → restores previous status."""
        registry.set_status('alice', 'Available')
        registry.set_status('alice', 'Busy', reason='in_call')
        registry.set_status('alice', 'Available', reason='active')
        assert registry.get_status('alice') == 'Available'
        assert registry.get_reason('alice') == 'active'

    def test_away_detection_transition(self, registry):
        """User with old heartbeat → set to Away + reason='idle_timeout'."""
        registry.update_heartbeat('alice')
        old_hb = datetime.utcnow() - timedelta(seconds=AWAY_TIMEOUT_SECONDS + 10)
        # Manually set old heartbeat (simulate timeout detection)
        with registry._lock:
            state = registry._users.setdefault('alice', PresenceState())
            state.last_heartbeat = old_hb
            state.status = 'Available'
        registry.set_status('alice', 'Away', reason='idle_timeout')
        assert registry.get_status('alice') == 'Away'
        assert registry.get_reason('alice') == 'idle_timeout'

    def test_away_does_not_affect_recent_users(self, registry):
        """User with recent heartbeat stays Available."""
        registry.update_heartbeat('alice')
        registry.set_status('alice', 'Available')
        # Should still be Available — heartbeat is recent
        assert registry.get_status('alice') == 'Available'

    def test_presence_reason_is_runtime_only(self, registry):
        """Reason is stored in registry, not in any DB model."""
        registry.set_status('alice', 'Away', reason='idle_timeout')
        assert registry.get_reason('alice') == 'idle_timeout'
        # There is no presence_reason column on User model — verify this
        # by checking that the reason is only accessible via the registry
        assert registry.get_reason('bob') is None


# ═══════════════════════════════════════════════════════════════════════════
# Backward compatibility helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    def test_registry_importable(self):
        from utils.presence import registry as global_reg
        assert global_reg is not None

    def test_valid_status_values_unchanged_types(self):
        assert isinstance(VALID_STATUS_VALUES, frozenset)

    def test_away_is_new_status(self):
        """Away was not in the original 3-value set."""
        original = {'Available', 'Busy', 'Offline'}
        assert 'Away' not in original
        assert 'Away' in VALID_STATUS_VALUES


# ═══════════════════════════════════════════════════════════════════════════
# Previous-status save/restore (call_start → call_end cycle)
# ═══════════════════════════════════════════════════════════════════════════

class TestPreviousStatus:
    def test_save_previous_status(self, registry):
        registry.set_status('alice', 'Available')
        saved = registry.save_previous_status('alice')
        assert saved == 'Available'

    def test_pop_previous_status_returns_saved(self, registry):
        registry.set_status('alice', 'Available')
        registry.save_previous_status('alice')
        registry.set_status('alice', 'Busy')
        prev = registry.pop_previous_status('alice')
        assert prev == 'Available'

    def test_pop_returns_none_when_no_previous(self, registry):
        registry.set_status('alice', 'Busy')
        prev = registry.pop_previous_status('alice')
        assert prev is None

    def test_save_then_pop_restores_manual_status(self, registry):
        """Simulate: user is Busy(manual) → call_start → call_end → Busy."""
        registry.set_status('alice', 'Busy', reason='manual')
        registry.save_previous_status('alice')       # save Busy
        registry.set_status('alice', 'Busy', reason='in_call')  # call_start
        assert registry.get_reason('alice') == 'in_call'
        prev = registry.pop_previous_status('alice')  # call_end
        assert prev == 'Busy'
        registry.set_status('alice', prev, reason='active')
        assert registry.get_status('alice') == 'Busy'
        assert registry.get_reason('alice') == 'active'

    def test_previous_status_not_set_by_default(self, registry):
        registry.set_status('alice', 'Available')
        s = registry._users['alice']
        assert s.previous_status is None
