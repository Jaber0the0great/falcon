import unittest
import tempfile
import os
import sqlite3
from unittest.mock import Mock, MagicMock
from utils.migration.resolver import detect_conflicts, generate_preview, apply_resolutions, ConflictReport, PreviewReport
from utils.migration.constants import ModelKeys


class TestConflictReport(unittest.TestCase):
    def test_add_entity(self):
        report = ConflictReport()
        report.add_entity("user", 10, ["alice", "bob"], {"existing_usernames": ["alice", "bob", "charlie"]})
        self.assertIn("user", report.entities)
        self.assertEqual(report.entities["user"]["total_in_source"], 10)
        self.assertEqual(report.entities["user"]["conflict_count"], 2)

    def test_to_dict(self):
        report = ConflictReport()
        report.add_entity("user", 5, [])
        d = report.to_dict()
        self.assertIn("entities", d)

    def test_has_conflicts_true(self):
        report = ConflictReport()
        report.add_entity("user", 5, ["alice"])
        self.assertTrue(report.has_conflicts())

    def test_has_conflicts_false(self):
        report = ConflictReport()
        report.add_entity("user", 5, [])
        self.assertFalse(report.has_conflicts())


class TestPreviewReport(unittest.TestCase):
    def test_add_entity(self):
        report = PreviewReport()
        report.add_entity("user", 15, 12, 9, 3, will_rename=0)
        self.assertEqual(report.entities["user"]["existing"], 15)
        self.assertEqual(report.entities["user"]["will_import"], 9)
        self.assertEqual(report.entities["user"]["will_skip"], 3)

    def test_to_dict(self):
        report = PreviewReport()
        report.add_entity("user", 0, 0, 0, 0)
        d = report.to_dict()
        self.assertIn("entities", d)


class TestDetectConflicts(unittest.TestCase):
    def setUp(self):
        self.target_models = {
            ModelKeys.USER: MagicMock(),
            ModelKeys.MESSAGE: MagicMock(),
            ModelKeys.GROUP: MagicMock(),
        }

        alice = MagicMock()
        alice.username = "alice"
        bob = MagicMock()
        bob.username = "bob"
        self.target_models[ModelKeys.USER].query.with_entities.return_value.all.return_value = [alice, bob]

        msg1 = MagicMock()
        msg1.msg_id = "m1"
        self.target_models[ModelKeys.MESSAGE].query.with_entities.return_value.all.return_value = [msg1]

        general = MagicMock()
        general.name = "general"
        self.target_models[ModelKeys.GROUP].query.with_entities.return_value.all.return_value = [general]

        self.tmp = tempfile.mkdtemp()
        self.source_path = os.path.join(self.tmp, "source.db")
        conn = sqlite3.connect(self.source_path)
        c = conn.cursor()
        c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT, msg_id TEXT, content TEXT)")
        c.execute("INSERT INTO messages VALUES ('alice', 'bob', 'm1', 'hello')")
        c.execute("INSERT INTO messages VALUES ('bob', 'alice', 'm2', 'hi')")
        c.execute("INSERT INTO messages VALUES ('charlie', 'alice', 'm3', 'hey')")
        c.execute("INSERT INTO messages VALUES ('server', 'All', 'm4', 'system')")
        conn.commit()
        conn.close()

        self.source_conn = sqlite3.connect(self.source_path)

    def tearDown(self):
        self.source_conn.close()
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_detect_user_conflicts(self):
        report = detect_conflicts(self.source_conn, None, self.target_models)
        self.assertIn("user", report.entities)
        user_report = report.entities["user"]
        self.assertIn("alice", user_report["conflicts"])
        self.assertIn("bob", user_report["conflicts"])
        self.assertNotIn("charlie", user_report["conflicts"])

    def test_detect_message_conflicts(self):
        report = detect_conflicts(self.source_conn, None, self.target_models)
        self.assertIn("message", report.entities)
        msg_report = report.entities["message"]
        self.assertIn("m1", msg_report["conflicts"])

    def test_detect_group_conflicts(self):
        report = detect_conflicts(self.source_conn, None, self.target_models)
        self.assertIn("group", report.entities)

    def test_has_conflicts(self):
        report = detect_conflicts(self.source_conn, None, self.target_models)
        self.assertTrue(report.has_conflicts())


class TestGeneratePreview(unittest.TestCase):
    def setUp(self):
        self.target_models = {
            ModelKeys.USER: MagicMock(),
            ModelKeys.MESSAGE: MagicMock(),
            ModelKeys.GROUP: MagicMock(),
        }

        self.target_models[ModelKeys.USER].query.count.return_value = 15
        alice = MagicMock()
        alice.username = "alice"
        bob = MagicMock()
        bob.username = "bob"
        self.target_models[ModelKeys.USER].query.with_entities.return_value.all.return_value = [alice, bob]

        self.target_models[ModelKeys.MESSAGE].query.count.return_value = 4000
        msg1 = MagicMock()
        msg1.msg_id = "m1"
        self.target_models[ModelKeys.MESSAGE].query.with_entities.return_value.all.return_value = [msg1]

        self.target_models[ModelKeys.GROUP].query.count.return_value = 3
        general = MagicMock()
        general.name = "general"
        self.target_models[ModelKeys.GROUP].query.with_entities.return_value.all.return_value = [general]

        self.tmp = tempfile.mkdtemp()
        self.source_path = os.path.join(self.tmp, "source.db")
        conn = sqlite3.connect(self.source_path)
        c = conn.cursor()
        c.execute("CREATE TABLE messages (sender TEXT, recipient TEXT, msg_id TEXT)")
        c.execute("INSERT INTO messages VALUES ('alice', 'bob', 'm1')")
        c.execute("INSERT INTO messages VALUES ('bob', 'alice', 'm2')")
        c.execute("INSERT INTO messages VALUES ('charlie', 'dave', 'm3')")
        c.execute("INSERT INTO messages VALUES ('eve', 'frank', 'm4')")
        conn.commit()
        conn.close()

        self.source_conn = sqlite3.connect(self.source_path)

    def tearDown(self):
        self.source_conn.close()
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_preview_counts(self):
        config = {
            "enabled": {"user": True, "message": True, "group": True},
            "policies": {"user": "skip", "message": "skip_duplicates", "group": "skip"},
        }
        report = generate_preview(self.source_conn, None, self.target_models, config)
        self.assertIn("user", report.entities)
        self.assertEqual(report.entities["user"]["existing"], 15)
        self.assertEqual(report.entities["user"]["incoming"], 6)
        self.assertEqual(report.entities["user"]["will_skip"], 2)
        self.assertEqual(report.entities["user"]["will_import"], 4)

    def test_preview_with_rename_policy(self):
        config = {
            "enabled": {"user": True, "message": True, "group": True},
            "policies": {"user": "rename", "message": "skip_duplicates", "group": "skip"},
        }
        report = generate_preview(self.source_conn, None, self.target_models, config)
        self.assertEqual(report.entities["user"]["will_rename"], 2)
        self.assertEqual(report.entities["user"]["will_import"], 4)


class TestApplyResolutions(unittest.TestCase):
    def test_user_skip(self):
        records = [{"username": "alice"}, {"username": "bob"}, {"username": "charlie"}]
        existing = {"alice", "bob"}
        result = apply_resolutions(records, "user", "skip", {"existing_usernames": existing})
        actions = [r[0] for r in result]
        self.assertEqual(actions, ["skip", "skip", "import"])

    def test_user_rename(self):
        records = [{"username": "alice"}, {"username": "bob"}]
        existing = {"alice"}
        result = apply_resolutions(records, "user", "rename", {"existing_usernames": existing})
        self.assertEqual(len(result), 2)
        action_alice, rec_alice = result[0]
        action_bob, rec_bob = result[1]
        self.assertEqual(action_alice, "import")
        self.assertNotEqual(rec_alice["username"], "alice")
        self.assertEqual(action_bob, "import")
        self.assertEqual(rec_bob["username"], "bob")

    def test_message_skip_duplicates(self):
        records = [{"msg_id": "m1"}, {"msg_id": "m2"}, {"msg_id": "m3"}]
        result = apply_resolutions(records, "message", "skip_duplicates", {"existing_msg_ids": {"m1", "m3"}})
        actions = [r[0] for r in result]
        self.assertEqual(actions, ["skip", "import", "skip"])

    def test_message_import_all(self):
        records = [{"msg_id": "m1"}, {"msg_id": "m2"}]
        result = apply_resolutions(records, "message", "import_all", {"existing_msg_ids": {"m1"}})
        actions = [r[0] for r in result]
        self.assertEqual(actions, ["import", "import"])

    def test_message_replace(self):
        records = [{"msg_id": "m1"}, {"msg_id": "m2"}]
        result = apply_resolutions(records, "message", "replace", {"existing_msg_ids": {"m1"}})
        actions = [r[0] for r in result]
        self.assertEqual(actions, ["replace", "import"])

    def test_group_rename(self):
        records = [{"name": "general"}, {"name": "random"}]
        result = apply_resolutions(records, "group", "rename", {"existing_names": {"general"}})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "import")
        self.assertEqual(result[0][1]["name"], "general (imported)")
        self.assertEqual(result[1][0], "import")
        self.assertEqual(result[1][1]["name"], "random")

    def test_group_merge(self):
        records = [{"name": "general"}, {"name": "random"}]
        result = apply_resolutions(records, "group", "merge", {"existing_names": {"general"}})
        actions = [r[0] for r in result]
        self.assertEqual(actions, ["skip", "import"])


class TestConflictReportSerialization(unittest.TestCase):
    def test_full_cycle(self):
        report = ConflictReport()
        report.add_entity("user", 10, ["alice", "bob"])
        report.add_entity("message", 100, [])
        report.add_entity("group", 3, ["general"])
        d = report.to_dict()
        self.assertEqual(len(d["entities"]), 3)
        self.assertTrue(report.has_conflicts())

        no_conflict = ConflictReport()
        no_conflict.add_entity("user", 5, [])
        self.assertFalse(no_conflict.has_conflicts())


if __name__ == '__main__':
    unittest.main()
