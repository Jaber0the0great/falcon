import unittest
import os
import sqlite3
import tempfile
import shutil
from utils.backup import create_backup, create_pre_import_backup, list_backups, restore_backup, prune_backups


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.backup_dir = os.path.join(self.tmpdir, "backups")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
        c.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_create_backup_success(self):
        result = create_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        self.assertTrue(result["success"])
        self.assertTrue(os.path.isfile(result["path"]))
        self.assertIn("Falcon_Backup_", result["filename"])
        self.assertTrue(result["filename"].endswith(".db"))

    def test_create_backup_content(self):
        result = create_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        conn = sqlite3.connect(result["path"])
        c = conn.cursor()
        c.execute("SELECT value FROM test WHERE id=1")
        row = c.fetchone()
        self.assertEqual(row[0], "hello")
        conn.close()

    def test_create_backup_nonexistent_db(self):
        result = create_backup(db_path=os.path.join(self.tmpdir, "nonexistent.db"), backup_dir=self.backup_dir)
        self.assertFalse(result["success"])

    def test_create_pre_import_backup(self):
        result = create_pre_import_backup("IMP-20260704-TEST", db_path=self.db_path, backup_dir=self.backup_dir)
        self.assertTrue(result["success"])
        self.assertIn("pre_import_IMP-20260704-TEST", result["filename"])

    def test_list_backups_empty(self):
        backups = list_backups(backup_dir=self.backup_dir)
        self.assertEqual(backups, [])

    def test_list_backups_with_files(self):
        create_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        create_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        backups = list_backups(backup_dir=self.backup_dir)
        self.assertEqual(len(backups), 2)

    def test_list_backups_metadata(self):
        create_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        create_pre_import_backup("IMP-001", db_path=self.db_path, backup_dir=self.backup_dir)
        backups = list_backups(backup_dir=self.backup_dir)
        self.assertTrue(any(b["is_pre_import"] for b in backups))
        for b in backups:
            self.assertIn("filename", b)
            self.assertIn("size", b)
            self.assertIn("mtime", b)

    def test_restore_backup(self):
        result = create_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        restore_path = os.path.join(self.tmpdir, "restored.db")
        restore = restore_backup(result["path"], target_path=restore_path)
        self.assertTrue(restore["success"])

        conn = sqlite3.connect(restore_path)
        c = conn.cursor()
        c.execute("SELECT value FROM test WHERE id=1")
        row = c.fetchone()
        self.assertEqual(row[0], "hello")
        conn.close()

    def test_restore_backup_nonexistent(self):
        result = restore_backup(os.path.join(self.tmpdir, "nonexistent.db"), target_path=self.db_path)
        self.assertFalse(result["success"])

    def test_prune_backups(self):
        for i in range(15):
            create_backup(db_path=self.db_path, label=f"backup_{i}", backup_dir=self.backup_dir)
        result = prune_backups(retain_count=5, backup_dir=self.backup_dir)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["deleted"]), 10)
        remaining = list_backups(backup_dir=self.backup_dir)
        self.assertLessEqual(len(remaining), 5)

    def test_prune_backups_below_retain(self):
        for i in range(3):
            create_backup(db_path=self.db_path, label=f"backup_{i}", backup_dir=self.backup_dir)
        result = prune_backups(retain_count=10, backup_dir=self.backup_dir)
        self.assertEqual(len(result["deleted"]), 0)

    def test_prune_backups_empty_dir(self):
        result = prune_backups(retain_count=5, backup_dir=self.backup_dir)
        self.assertEqual(len(result["deleted"]), 0)


if __name__ == "__main__":
    unittest.main()
