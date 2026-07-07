import unittest
import tempfile
import os
import sqlite3
from utils.migration.validator import validate_schema, check_integrity, check_column_compatibility, ValidationIssue


def build_v1_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, status TEXT, created_at TIMESTAMP, last_seen TIMESTAMP, is_banned INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL, msg_type TEXT NOT NULL, content TEXT, time TEXT, duration INTEGER, file_name TEXT, raw_data TEXT, status TEXT DEFAULT 'sent', msg_id TEXT UNIQUE NOT NULL, reactions TEXT DEFAULT '{}', reply_to TEXT, reply_content TEXT, deleted_by_sender INTEGER DEFAULT 0, deleted_by_recipient INTEGER DEFAULT 0, created_at TIMESTAMP)")
    c.execute("CREATE TABLE `group` (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT, owner_username TEXT NOT NULL, created_at TIMESTAMP)")
    c.execute("CREATE TABLE group_member (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, joined_at TIMESTAMP)")
    c.execute("CREATE TABLE group_invite (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, status TEXT DEFAULT 'pending', invited_by TEXT NOT NULL)")
    c.execute("CREATE TABLE group_join_request (id INTEGER PRIMARY KEY, group_name TEXT NOT NULL, username TEXT NOT NULL, status TEXT DEFAULT 'pending')")
    c.execute("CREATE TABLE system_broadcast (id INTEGER PRIMARY KEY, message TEXT NOT NULL, created_at TIMESTAMP, is_sent INTEGER DEFAULT 0)")
    conn.commit()
    conn.close()


def build_incomplete_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, status TEXT)")
    c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL, msg_type TEXT NOT NULL, content TEXT, time TEXT, msg_id TEXT UNIQUE NOT NULL)")
    conn.commit()
    conn.close()


def build_legacy_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT, content TEXT, time TEXT, msg_type TEXT, msg_id TEXT)")
    conn.commit()
    conn.close()


def build_partial_legacy_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT, content TEXT)")
    conn.commit()
    conn.close()


class TestValidateSchemaV1(unittest.TestCase):
    def test_full_v1_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            build_v1_db(path)
            conn = sqlite3.connect(path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {}
            for row in cur.fetchall():
                name = row[0]
                cur2 = conn.execute(f"PRAGMA table_info(`{name}`)")
                cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])} for r in cur2.fetchall()]
                tables[name] = {"columns": cols}
            conn.close()

            issues = validate_schema(tables, "v1.0")
            errors = [i for i in issues if i.severity == "error"]
            warnings = [i for i in issues if i.severity == "warning"]
            self.assertEqual(len(errors), 0, msg=f"Errors: {errors}")
            self.assertEqual(len(warnings), 0, msg=f"Warnings: {warnings}")

    def test_incomplete_v1_has_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            build_incomplete_db(path)
            conn = sqlite3.connect(path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {}
            for row in cur.fetchall():
                name = row[0]
                cur2 = conn.execute(f"PRAGMA table_info(`{name}`)")
                cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])} for r in cur2.fetchall()]
                tables[name] = {"columns": cols}
            conn.close()

            issues = validate_schema(tables, "v1.0")
            errors = [i for i in issues if i.severity == "error"]
            self.assertGreater(len(errors), 0, msg="Expected missing table errors")

    def test_missing_group_tables_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            build_incomplete_db(path)
            conn = sqlite3.connect(path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {}
            for row in cur.fetchall():
                name = row[0]
                cur2 = conn.execute(f"PRAGMA table_info(`{name}`)")
                cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])} for r in cur2.fetchall()]
                tables[name] = {"columns": cols}
            conn.close()

            issues = validate_schema(tables, "v1.0")
            warnings = [i for i in issues if i.severity == "warning" and i.code == "MISSING_TABLE"]
            self.assertGreater(len(warnings), 0, msg="Expected missing table warnings for group, group_member, etc.")


class TestValidateSchemaLegacy(unittest.TestCase):
    def test_legacy_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            build_legacy_db(path)
            conn = sqlite3.connect(path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {}
            for row in cur.fetchall():
                name = row[0]
                cur2 = conn.execute(f"PRAGMA table_info(`{name}`)")
                cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])} for r in cur2.fetchall()]
                tables[name] = {"columns": cols}
            conn.close()

            issues = validate_schema(tables, "legacy")
            errors = [i for i in issues if i.severity == "error"]
            self.assertEqual(len(errors), 0, msg=f"Errors: {errors}")

    def test_legacy_partial_has_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            build_partial_legacy_db(path)
            conn = sqlite3.connect(path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {}
            for row in cur.fetchall():
                name = row[0]
                cur2 = conn.execute(f"PRAGMA table_info(`{name}`)")
                cols = [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])} for r in cur2.fetchall()]
                tables[name] = {"columns": cols}
            conn.close()

            issues = validate_schema(tables, "legacy")
            warnings = [i for i in issues if i.severity == "warning"]
            infos = [i for i in issues if i.severity == "info"]
            self.assertGreater(len(warnings) + len(infos), 0, msg="Expected warnings/infos for missing columns")


class TestValidateSchemaUnknown(unittest.TestCase):
    def test_empty_tables(self):
        issues = validate_schema({}, "unknown")
        self.assertTrue(any(i.code == "NO_TABLES" for i in issues))

    def test_unknown_recognizes_known_tables(self):
        tables = {"user": {"columns": [{"name": "id"}]}, "random_table": {"columns": []}}
        issues = validate_schema(tables, "unknown")
        self.assertTrue(any(i.code == "RECOGNIZED_TABLE" for i in issues))
        self.assertTrue(any(i.code == "UNRECOGNIZED_TABLE" for i in issues))


class TestCheckColumnCompatibility(unittest.TestCase):
    def test_compatible(self):
        source = [{"name": "id"}, {"name": "username"}, {"name": "password_hash"}]
        expected = ["id", "username", "password_hash"]
        result = check_column_compatibility(source, expected)
        self.assertTrue(result["compatible"])
        self.assertEqual(len(result["missing"]), 0)

    def test_missing_columns(self):
        source = [{"name": "id"}, {"name": "username"}]
        expected = ["id", "username", "password_hash"]
        result = check_column_compatibility(source, expected)
        self.assertFalse(result["compatible"])
        self.assertIn("password_hash", result["missing"])

    def test_extra_columns(self):
        source = [{"name": "id"}, {"name": "username"}, {"name": "extra_col"}]
        expected = ["id", "username"]
        result = check_column_compatibility(source, expected)
        self.assertTrue(result["compatible"])
        self.assertIn("extra_col", result["extra"])


class TestValidationIssue(unittest.TestCase):
    def test_to_dict(self):
        issue = ValidationIssue("error", "TEST_CODE", "Test message", table="user", column="username")
        d = issue.to_dict()
        self.assertEqual(d["severity"], "error")
        self.assertEqual(d["code"], "TEST_CODE")
        self.assertEqual(d["table"], "user")
        self.assertEqual(d["column"], "username")

    def test_repr(self):
        issue = ValidationIssue("warning", "TEST", "msg")
        self.assertIn("WARNING", repr(issue))
        self.assertIn("TEST", repr(issue))


if __name__ == '__main__':
    unittest.main()
