"""Tests for the runtime TypingTracker (in-memory, no database)."""

import pytest
from utils.typing import TypingTracker


@pytest.fixture
def tracker():
    return TypingTracker()


class TestTypingTracker:
    def test_start_private_returns_room(self, tracker):
        room = tracker.start('alice', 'bob', 'private')
        assert room == 'bob'

    def test_start_group_returns_room(self, tracker):
        room = tracker.start('alice', 'gamers', 'group')
        assert room == 'gamers'

    def test_start_duplicate_returns_none(self, tracker):
        tracker.start('alice', 'bob', 'private')
        room = tracker.start('alice', 'bob', 'private')
        assert room is None

    def test_stop_private_returns_room(self, tracker):
        tracker.start('alice', 'bob', 'private')
        room = tracker.stop('alice', 'bob', 'private')
        assert room == 'bob'

    def test_stop_when_not_typing_returns_none(self, tracker):
        room = tracker.stop('alice', 'bob', 'private')
        assert room is None

    def test_typing_users_includes_typer(self, tracker):
        tracker.start('alice', 'bob', 'private')
        users = tracker.typing_users('bob', 'alice', 'private')
        assert users == {'alice'}

    def test_typing_users_empty_in_unrelated_conversation(self, tracker):
        tracker.start('alice', 'bob', 'private')
        # Charlie's conversation with Bob is separate
        users = tracker.typing_users('bob', 'charlie', 'private')
        assert users == set()

    def test_typing_users_excludes_self(self, tracker):
        tracker.start('alice', 'bob', 'private')
        users = tracker.typing_users('alice', 'bob', 'private')
        assert 'alice' not in users

    def test_typing_users_empty_when_none(self, tracker):
        users = tracker.typing_users('alice', 'bob', 'private')
        assert users == set()

    def test_clear_user_returns_private_rooms(self, tracker):
        tracker.start('alice', 'bob', 'private')
        tracker.start('alice', 'charlie', 'private')
        result = tracker.clear_user('alice')
        assert len(result) == 2
        rooms = {r for r, t in result}
        assert 'bob' in rooms
        assert 'charlie' in rooms

    def test_clear_user_returns_group_rooms(self, tracker):
        tracker.start('alice', 'gamers', 'group')
        result = tracker.clear_user('alice')
        assert len(result) == 1
        assert result[0] == ('gamers', 'group')

    def test_clear_user_only_removes_user_own_typing(self, tracker):
        """Alice and Charlie typing in separate conversations with Bob
        are independent; clearing Alice does not affect Charlie."""
        tracker.start('alice', 'bob', 'private')
        tracker.start('charlie', 'bob', 'private')
        tracker.clear_user('alice')
        # Alice is gone from her chat with Bob
        users_alice = tracker.typing_users('bob', 'alice', 'private')
        assert users_alice == set()
        # Charlie still typing in his chat with Bob
        users_charlie = tracker.typing_users('bob', 'charlie', 'private')
        assert users_charlie == {'charlie'}

    def test_clear_user_noop_when_not_typing(self, tracker):
        result = tracker.clear_user('alice')
        assert result == []

    def test_start_group_then_stop_cleans_up(self, tracker):
        tracker.start('alice', 'gamers', 'group')
        tracker.stop('alice', 'gamers', 'group')
        users = tracker.typing_users('bob', 'gamers', 'group')
        assert users == set()

    def test_multiple_typers_same_group(self, tracker):
        tracker.start('alice', 'gamers', 'group')
        tracker.start('charlie', 'gamers', 'group')
        tracker.start('bob', 'gamers', 'group')
        users = tracker.typing_users('bob', 'gamers', 'group')
        assert users == {'alice', 'charlie'}

    def test_private_conversations_independent(self, tracker):
        tracker.start('alice', 'bob', 'private')
        tracker.start('alice', 'charlie', 'private')
        # Stopping bob should not affect charlie
        tracker.stop('alice', 'bob', 'private')
        users_bob = tracker.typing_users('bob', 'alice', 'private')
        users_charlie = tracker.typing_users('charlie', 'alice', 'private')
        assert users_bob == set()
        assert 'alice' in users_charlie

    def test_thread_safety(self, tracker):
        """Rapid concurrent start/stop does not raise."""
        import threading
        errors = []

        def hammer():
            for i in range(50):
                try:
                    t = f"user{i}"
                    tracker.start(t, 'bob', 'private')
                    tracker.stop(t, 'bob', 'private')
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
