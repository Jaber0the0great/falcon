import unittest
import os
import sqlite3
import tempfile
import json
from utils.migration.scanner import scan, detect_version, extract_users_from_messages


def build_v1_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, status TEXT DEFAULT 'Available', created_at TIMESTAMP, last_seen TIMESTAMP, is_banned INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL, msg_type TEXT NOT NULL, content TEXT, time TEXT, duration INTEGER, file_name TEXT, raw_data TEXT, status TEXT DEFAULT 'sent', msg_id TEXT UNIQUE NOT NULL, reactions TEXT DEFAULT '{}', reply_to TEXT, reply_content TEXT, deleted_by_sender INTEGER DEFAULT 0, deleted_by_recipient INTEGER DEFAULT 0, created_at TIMESTAMP)")
    c.execute("CREATE TABLE `group` (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT, owner_username TEXT NOT NULL, created_at TIMESTAMP)")
    c.execute("CREATE TABLE group_member (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, joined_at TIMESTAMP)")
    c.execute("CREATE TABLE group_invite (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, status TEXT DEFAULT 'pending', invited_by TEXT NOT NULL)")
    c.execute("CREATE TABLE group_join_request (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, status TEXT DEFAULT 'pending')")
    c.execute("CREATE TABLE system_broadcast (id INTEGER PRIMARY KEY, message TEXT NOT NULL, created_at TIMESTAMP, is_sent INTEGER DEFAULT 0)")

    c.execute("INSERT INTO user (username, password_hash, status) VALUES ('alice', 'hash1', 'Available')")
    c.execute("INSERT INTO user (username, password_hash, status) VALUES ('bob', 'hash2', 'Busy')")
    c.execute("INSERT INTO user (username, password_hash, status, is_admin) VALUES ('charlie', 'hash3', 'Offline', 1)")

    c.execute("INSERT INTO message (sender, recipient, msg_type, content, time, msg_id) VALUES ('alice', 'bob', 'text', 'Hello', '2024-01-15T10:00:00', 'm1')")
    c.execute("INSERT INTO message (sender, recipient, msg_type, content, time, msg_id) VALUES ('bob', 'alice', 'text', 'Hi', '2024-01-15T10:01:00', 'm2')")
    c.execute("INSERT INTO message (sender, recipient, msg_type, content, time, msg_id) VALUES ('alice', 'bob', 'file', 'image.png', '2024-01-15T10:02:00', 'm3')")

    c.execute("INSERT INTO `group` (name, description, owner_username) VALUES ('general', 'General chat', 'alice')")
    c.execute("INSERT INTO group_member (group_name, username) VALUES ('general', 'alice')")
    c.execute("INSERT INTO group_member (group_name, username) VALUES ('general', 'bob')")

    conn.commit()
    conn.close()


def build_legacy_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT, content TEXT, time TEXT, msg_type TEXT, msg_id TEXT, file_name TEXT, raw_data TEXT, status TEXT, reactions TEXT, reply_to TEXT, reply_content TEXT, duration INTEGER)")
    c.execute("INSERT INTO messages (sender, recipient, content, time, msg_type, msg_id) VALUES ('alice', 'bob', 'Hello legacy', '2024-06-01T12:00:00', 'text', 'lm1')")
    c.execute("INSERT INTO messages (sender, recipient, content, time, msg_type, msg_id) VALUES ('bob', 'alice', 'Hi legacy', '2024-06-01T12:01:00', 'text', 'lm2')")
    c.execute("INSERT INTO messages (sender, recipient, content, time, msg_type, msg_id) VALUES ('server', 'All', 'System msg', '2024-06-01T12:02:00', 'system', 'lm3')")
    conn.commit()
    conn.close()


def build_corrupted_db(path):
    with open(path, 'wb') as f:
        f.write(b'\x00' * 1024)


def build_non_sqlite(path):
    with open(path, 'w') as f:
        f.write("This is not a database file.")


class TestScannerV1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.v1_path = os.path.join(self.tmp, "falcon_v1.db")
        build_v1_db(self.v1_path)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_scan_v1_db(self):
        result = scan(self.v1_path)
        self.assertNotIn("error", result, msg=result.get("error", ""))
        self.assertEqual(result["version_detected"], "v1.0")
        self.assertIn("tables", result)
        self.assertIn("user", result["tables"])
        self.assertIn("message", result["tables"])
        self.assertIn("group", result["tables"])
        self.assertIn("group_member", result["tables"])
        self.assertIn("group_invite", result["tables"])
        self.assertIn("group_join_request", result["tables"])
        self.assertIn("system_broadcast", result["tables"])

    def test_v1_row_counts(self):
        result = scan(self.v1_path)
        self.assertEqual(result["tables"]["user"]["records"], 3)
        self.assertEqual(result["tables"]["message"]["records"], 3)
        self.assertEqual(result["tables"]["group"]["records"], 1)
        self.assertEqual(result["tables"]["group_member"]["records"], 2)

    def test_v1_column_count(self):
        result = scan(self.v1_path)
        self.assertEqual(len(result["tables"]["user"]["columns"]), 8)
        self.assertEqual(len(result["tables"]["message"]["columns"]), 17)

    def test_v1_admin_count(self):
        result = scan(self.v1_path)
        self.assertEqual(result["admin_count"], 1)

    def test_v1_message_types(self):
        result = scan(self.v1_path)
        self.assertEqual(result["message_types"], {"text": 2, "file": 1})

    def test_v1_date_range(self):
        result = scan(self.v1_path)
        self.assertIsNotNone(result["date_range"])
        self.assertEqual(result["date_range"]["earliest"], "2024-01-15T10:00:00")
        self.assertEqual(result["date_range"]["latest"], "2024-01-15T10:02:00")


class TestScannerLegacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.legacy_path = os.path.join(self.tmp, "chat_history.db")
        build_legacy_db(self.legacy_path)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_scan_legacy_db(self):
        result = scan(self.legacy_path)
        self.assertNotIn("error", result, msg=result.get("error", ""))
        self.assertEqual(result["version_detected"], "legacy")

    def test_legacy_extracted_users(self):
        result = scan(self.legacy_path)
        self.assertIn("extracted_users", result)
        self.assertIn("alice", result["extracted_users"])
        self.assertIn("bob", result["extracted_users"])
        self.assertNotIn("Server", result["extracted_users"])
        self.assertNotIn("All", result["extracted_users"])

    def test_legacy_row_count(self):
        result = scan(self.legacy_path)
        self.assertEqual(result["tables"]["messages"]["records"], 3)


class TestScannerErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.nonexistent = os.path.join(self.tmp, "nonexistent.db")
        self.corrupted = os.path.join(self.tmp, "corrupted.db")
        build_corrupted_db(self.corrupted)
        self.not_sqlite = os.path.join(self.tmp, "not_sqlite.txt")
        build_non_sqlite(self.not_sqlite)
        self.empty = os.path.join(self.tmp, "empty.db")
        with open(self.empty, 'wb') as f:
            pass

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_nonexistent_file(self):
        result = scan(self.nonexistent)
        self.assertIn("error", result)
        self.assertIn("not found", result["error"].lower())

    def test_not_sqlite(self):
        result = scan(self.not_sqlite)
        self.assertIn("error", result)
        self.assertIn("magic bytes", result["error"].lower())

    def test_empty_file(self):
        result = scan(self.empty)
        self.assertIn("error", result)
        self.assertIn("empty", result["error"].lower())

    def test_corrupted_db(self):
        result = scan(self.corrupted)
        self.assertIn("error", result)


class TestDetectVersion(unittest.TestCase):
    def test_v1_full(self):
        tables = {"user": {}, "message": {}, "group": {}, "group_member": {}, "group_invite": {}, "group_join_request": {}, "system_broadcast": {}}
        self.assertEqual(detect_version(tables), "v1.0")

    def test_v1_minimal(self):
        tables = {"user": {}, "message": {}, "group": {}}
        self.assertEqual(detect_version(tables), "v1.0")

    def test_v1_user_message(self):
        tables = {"user": {}, "message": {}}
        self.assertEqual(detect_version(tables), "v1.0")

    def test_legacy_messages(self):
        tables = {"messages": {}}
        self.assertEqual(detect_version(tables), "legacy")

    def test_empty(self):
        tables = {}
        self.assertEqual(detect_version(tables), "empty")

    def test_unknown(self):
        tables = {"some_random_table": {}}
        self.assertEqual(detect_version(tables), "unknown")


class TestExtractUsers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "test.db")
        conn = sqlite3.connect(self.path)
        c = conn.cursor()
        c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT)")
        c.execute("INSERT INTO messages VALUES ('alice', 'bob')")
        c.execute("INSERT INTO messages VALUES ('bob', 'alice')")
        c.execute("INSERT INTO messages VALUES ('server', 'All')")
        c.execute("INSERT INTO messages VALUES ('Server', 'all')")
        c.execute("INSERT INTO messages VALUES ('charlie', 'bob')")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.remove(self.path)
        os.rmdir(self.tmp)

    def test_extract_users(self):
        conn = sqlite3.connect(self.path)
        users = extract_users_from_messages(conn)
        conn.close()
        self.assertIn("alice", users)
        self.assertIn("bob", users)
        self.assertIn("charlie", users)
        self.assertNotIn("server", users)
        self.assertNotIn("Server", users)
        self.assertNotIn("All", users)
        self.assertNotIn("all", users)
        self.assertEqual(len(users), 3)


if __name__ == '__main__':
    unittest.main()
