import unittest
import os
import sqlite3
import tempfile
import time
import json
from app import create_app
from database.database import db
from models.models import User, Message, Group, GroupMember, GroupInvite, GroupJoinRequest, SystemBroadcast
from config import Config

from utils.migration.importer import run_import, cancel_import, get_import_status, import_progress


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key-for-testing-only'


def build_test_source(path, include_all=True):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS user (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, status TEXT DEFAULT 'Available', created_at TIMESTAMP, last_seen TIMESTAMP, is_banned INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS message (id INTEGER PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL, msg_type TEXT NOT NULL, content TEXT, time TEXT, duration INTEGER, file_name TEXT, raw_data TEXT, status TEXT DEFAULT 'sent', msg_id TEXT UNIQUE NOT NULL, reactions TEXT DEFAULT '{}', reply_to TEXT, reply_content TEXT, deleted_by_sender INTEGER DEFAULT 0, deleted_by_recipient INTEGER DEFAULT 0, created_at TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS `group` (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT, owner_username TEXT NOT NULL, created_at TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS group_member (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, joined_at TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS group_invite (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, status TEXT DEFAULT 'pending', invited_by TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS group_join_request (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, status TEXT DEFAULT 'pending')")
    c.execute("CREATE TABLE IF NOT EXISTS system_broadcast (id INTEGER PRIMARY KEY, message TEXT NOT NULL, created_at TIMESTAMP, is_sent INTEGER DEFAULT 0)")

    c.execute("INSERT INTO user (username, password_hash, status) VALUES ('alice', 'hash1', 'Available')")
    c.execute("INSERT INTO user (username, password_hash, status) VALUES ('bob', 'hash2', 'Busy')")
    c.execute("INSERT INTO user (username, password_hash, status, is_admin) VALUES ('charlie', 'hash3', 'Offline', 1)")

    c.execute("INSERT INTO message (sender, recipient, msg_type, content, time, msg_id) VALUES ('alice', 'bob', 'text', 'Hello', '2024-01-15T10:00:00', 'm1')")
    c.execute("INSERT INTO message (sender, recipient, msg_type, content, time, msg_id) VALUES ('bob', 'alice', 'text', 'Hi', '2024-01-15T10:01:00', 'm2')")

    c.execute("INSERT INTO `group` (name, description, owner_username) VALUES ('general', 'General chat', 'alice')")
    c.execute("INSERT INTO group_member (group_name, username) VALUES ('general', 'alice')")
    c.execute("INSERT INTO group_member (group_name, username) VALUES ('general', 'bob')")
    c.execute("INSERT INTO group_invite (group_name, username, status, invited_by) VALUES ('general', 'charlie', 'pending', 'alice')")
    c.execute("INSERT INTO group_join_request (group_name, username, status) VALUES ('general', 'charlie', 'pending')")
    c.execute("INSERT INTO system_broadcast (message, is_sent) VALUES ('Welcome!', 1)")

    conn.commit()
    conn.close()


def build_legacy_source(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT, content TEXT, time TEXT, msg_type TEXT, msg_id TEXT, file_name TEXT, raw_data TEXT, status TEXT, reactions TEXT, reply_to TEXT, reply_content TEXT, duration INTEGER)")
    c.execute("INSERT INTO messages (sender, recipient, content, time, msg_type, msg_id) VALUES ('dave', 'eve', 'Hello legacy', '2024-06-01T12:00:00', 'text', 'lm1')")
    c.execute("INSERT INTO messages (sender, recipient, content, time, msg_type, msg_id) VALUES ('eve', 'dave', 'Hi back', '2024-06-01T12:01:00', 'text', 'lm2')")
    conn.commit()
    conn.close()


class TestImporterBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.source_fd, self.source_path = tempfile.mkstemp(suffix=".db")
        os.close(self.source_fd)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        if os.path.exists(self.source_path):
            os.unlink(self.source_path)


class TestImporterRun(TestImporterBase):
    def test_import_v1_full(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        self.assertEqual(status["status"], "completed")
        self.assertEqual(User.query.count(), 3)
        self.assertEqual(Message.query.count(), 2)
        self.assertEqual(Group.query.count(), 1)
        self.assertEqual(GroupMember.query.count(), 2)
        self.assertEqual(GroupInvite.query.count(), 1)
        self.assertEqual(GroupJoinRequest.query.count(), 1)
        self.assertEqual(SystemBroadcast.query.count(), 1)

    def test_import_v1_with_skipped_tables(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
            "enabled": {"user": False, "message": False, "group": False, "group_member": False,
                        "group_invite": False, "group_join_request": False, "system_broadcast": False},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(User.query.count(), 0)

    def test_import_v1_with_existing_data(self):
        u = User(username="alice")
        u.set_password("pass")
        db.session.add(u)
        db.session.commit()

        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(User.query.count(), 3)
        alice = User.query.filter_by(username="alice").first()
        self.assertIsNotNone(alice)
        self.assertEqual(Message.query.count(), 2)

    def test_import_legacy_messages(self):
        build_legacy_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "import_all", "group": "skip"},
            "enabled": {"user": False, "message": True, "group": False, "group_member": False,
                        "group_invite": False, "group_join_request": False, "system_broadcast": False},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(Message.query.count(), 2)
        results = status.get("results", {})
        msg_results = results.get("message", {})
        self.assertEqual(msg_results.get("imported"), 2)

    def test_import_nonexistent_source(self):
        config = {
            "policies": {},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import("nonexistent.db", config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "failed")
        self.assertIn("not found", status.get("error", "").lower())


class TestImporterCancel(TestImporterBase):
    def test_cancel_during_import(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        time.sleep(0.05)
        result = cancel_import(import_id)
        self.assertTrue(result["found"])

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertIn(status["status"], ("completed", "cancelled"))

    def test_cancel_not_found(self):
        result = cancel_import("NONEXISTENT")
        self.assertFalse(result["found"])

    def test_cancel_not_in_progress(self):
        import_progress["TEST_DONE"] = {
            "status": "completed",
            "progress_pct": 100,
            "tables": {},
            "cancel": False,
            "error": None,
            "import_id": "TEST_DONE",
            "results": {},
        }
        result = cancel_import("TEST_DONE")
        self.assertTrue(result["found"])
        self.assertIn("not in progress", result["message"].lower())


class TestImporterStatus(TestImporterBase):
    def test_get_status_not_found(self):
        self.assertIsNone(get_import_status("NONEXISTENT"))

    def test_get_status_returns_fields(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertIsNotNone(status)
        self.assertIn("import_id", status)
        self.assertIn("status", status)
        self.assertIn("progress_pct", status)
        self.assertIn("tables", status)
        self.assertIn("results", status)


class TestImporterDataIntegrity(TestImporterBase):
    def test_import_user_password_hashes(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "import_all", "group": "skip"},
            "enabled": {"user": True, "message": False, "group": False, "group_member": False,
                        "group_invite": False, "group_join_request": False, "system_broadcast": False},
            "default_password": "fallback_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")

        alice = User.query.filter_by(username="alice").first()
        bob = User.query.filter_by(username="bob").first()
        charlie = User.query.filter_by(username="charlie").first()

        self.assertIsNotNone(alice)
        self.assertEqual(alice.status, "Available")
        self.assertFalse(alice.is_admin)
        self.assertTrue(charlie.is_admin)

    def test_import_message_order_and_content(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "import_all", "group": "skip"},
            "enabled": {"user": True, "message": True, "group": False, "group_member": False,
                        "group_invite": False, "group_join_request": False, "system_broadcast": False},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        msgs = Message.query.order_by(Message.time).all()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content, "Hello")
        self.assertEqual(msgs[0].sender, "alice")
        self.assertEqual(msgs[0].recipient, "bob")
        self.assertEqual(msgs[1].content, "Hi")

    def test_import_correct_table_results(self):
        build_test_source(self.source_path)
        config = {
            "policies": {"user": "skip", "message": "import_all", "group": "rename"},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")
        results = status.get("results", {})
        self.assertIn("user", results)
        self.assertIn("message", results)
        self.assertIn("group", results)
        self.assertEqual(results["user"]["imported"], 3)
        self.assertEqual(results["message"]["imported"], 2)
        self.assertEqual(results["group"]["imported"], 1)


class TestImporterErrorHandling(TestImporterBase):
    def test_import_empty_source_db(self):
        conn = sqlite3.connect(self.source_path)
        conn.close()

        config = {
            "policies": {},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")

    def test_import_duplicate_msg_ids_skip_duplicates(self):
        build_test_source(self.source_path)

        msg = Message(
            sender="existing", recipient="user", msg_type="text",
            content="Existing message", msg_id="m1"
        )
        db.session.add(msg)
        db.session.commit()

        config = {
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
            "enabled": {"user": True, "message": True, "group": True, "group_member": True,
                        "group_invite": True, "group_join_request": True, "system_broadcast": True},
            "default_password": "import_pass",
        }
        import_id = run_import(self.source_path, config, self.app)

        for _ in range(50):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.1)

        status = get_import_status(import_id)
        self.assertEqual(status["status"], "completed")
        results = status.get("results", {}).get("message", {})
        self.assertEqual(results["imported"], 1)
        self.assertEqual(results["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
