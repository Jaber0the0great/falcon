import unittest
import os
import json
import sqlite3
import tempfile
import shutil
import zipfile
from utils.backup_center import (
    build_manifest,
    get_db_stats,
    get_schema_version,
    create_full_backup,
    restore_backup_full,
    verify_restore,
    check_compatibility,
    get_backup_summary,
    apply_retention,
    _check_db_integrity,
    _verify_entity,
)
from utils.backup import (
    create_quick_backup,
    list_backups,
    search_backups,
    verify_backup_file,
    prune_backups,
    QUICK_SUBDIR,
    FULL_SUBDIR,
)


class TestBackupCenterManifest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "falcon_web.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT)")
        c.execute("INSERT INTO user VALUES (1, 'alice')")
        c.execute("INSERT INTO user VALUES (2, 'bob')")
        c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, content TEXT)")
        c.execute("INSERT INTO message VALUES (1, 'hello')")
        c.execute("INSERT INTO message VALUES (2, 'world')")
        conn.commit()
        conn.close()

        self.uploads_dir = os.path.join(self.tmpdir, "uploads")
        os.makedirs(self.uploads_dir, exist_ok=True)
        with open(os.path.join(self.uploads_dir, "test.txt"), "w") as f:
            f.write("upload test")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_build_manifest_quick(self):
        manifest = build_manifest("quick", self.db_path)
        self.assertEqual(manifest["backup_type"], "quick")
        self.assertIn("created_at", manifest)
        self.assertIn("application_version", manifest)
        self.assertIn("database_schema_version", manifest)
        self.assertIn("sha256", manifest)
        self.assertIn("database", manifest["contents"])
        self.assertIn("database_statistics", manifest)

    def test_build_manifest_full(self):
        manifest = build_manifest("full", self.db_path, self.uploads_dir)
        self.assertEqual(manifest["backup_type"], "full")
        self.assertIn("uploads", manifest["contents"])
        self.assertEqual(manifest["contents"]["uploads"]["count"], 1)

    def test_build_manifest_no_db(self):
        manifest = build_manifest("quick", "/nonexistent/path.db")
        self.assertEqual(manifest["sha256"], "")
        self.assertEqual(manifest["contents"]["database"]["size_bytes"], 0)

    def test_manifest_contains_stats(self):
        manifest = build_manifest("quick", self.db_path)
        stats = manifest["database_statistics"]
        self.assertEqual(stats.get("total_user"), 2)
        self.assertEqual(stats.get("total_message"), 2)


class TestBackupCenterDbStats(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO user VALUES (1)")
        c.execute("INSERT INTO user VALUES (2)")
        c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_get_db_stats(self):
        stats = get_db_stats(self.db_path)
        self.assertEqual(stats.get("total_user"), 2)
        self.assertEqual(stats.get("total_message"), 0)
        self.assertEqual(stats.get("total_rows"), 2)

    def test_get_db_stats_missing_file(self):
        stats = get_db_stats("/nonexistent.db")
        self.assertEqual(stats, {})

    def test_get_schema_version(self):
        version = get_schema_version(self.db_path)
        self.assertEqual(version, 2)

    def test_get_schema_version_missing(self):
        version = get_schema_version("/nonexistent.db")
        self.assertEqual(version, 0)


class TestBackupCenterFullBackup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "falcon_web.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT)")
        c.execute("INSERT INTO user VALUES (1, 'alice')")
        c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, content TEXT)")
        c.execute("INSERT INTO message VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        self.uploads_dir = os.path.join(self.tmpdir, "uploads")
        os.makedirs(self.uploads_dir, exist_ok=True)
        for fname in ("a.txt", "b.txt", "sub/c.txt"):
            path = os.path.join(self.uploads_dir, fname)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(fname)

        self.backup_dir = os.path.join(self.tmpdir, "backups")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_create_full_backup_creates_zip(self):
        result = create_full_backup(db_path=self.db_path, uploads_dir=self.uploads_dir, backup_dir=self.backup_dir)
        self.assertTrue(result["success"])
        self.assertTrue(os.path.isfile(result["path"]))
        self.assertEqual(result["type"], "full")
        self.assertIn(".zip", result["filename"])
        self.assertIn("sha256", result)

    def test_full_backup_zip_contents(self):
        result = create_full_backup(db_path=self.db_path, uploads_dir=self.uploads_dir, backup_dir=self.backup_dir)
        with zipfile.ZipFile(result["path"], "r") as zf:
            names = zf.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("falcon_web.db", names)
            self.assertIn("uploads/a.txt", names)
            self.assertIn("uploads/b.txt", names)
            self.assertIn("uploads/sub/c.txt", names)

    def test_full_backup_manifest_content(self):
        result = create_full_backup(db_path=self.db_path, uploads_dir=self.uploads_dir, backup_dir=self.backup_dir)
        with zipfile.ZipFile(result["path"], "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["backup_type"], "full")
        self.assertEqual(manifest["contents"]["uploads"]["count"], 3)
        self.assertGreater(manifest["contents"]["uploads"]["size_bytes"], 0)

    def test_full_backup_no_uploads(self):
        result = create_full_backup(db_path=self.db_path, uploads_dir=None, backup_dir=self.backup_dir)
        self.assertTrue(result["success"])
        with zipfile.ZipFile(result["path"], "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        self.assertNotIn("uploads", manifest["contents"])

    def test_full_backup_no_source_db(self):
        result = create_full_backup(db_path="/nonexistent.db", uploads_dir=self.uploads_dir, backup_dir=self.backup_dir)
        self.assertFalse(result["success"])

    def test_full_backup_sidecar_sha256(self):
        result = create_full_backup(db_path=self.db_path, uploads_dir=self.uploads_dir, backup_dir=self.backup_dir)
        sha_path = result["path"] + ".sha256"
        self.assertTrue(os.path.isfile(sha_path))

    def test_full_backup_sidecar_manifest(self):
        result = create_full_backup(db_path=self.db_path, uploads_dir=self.uploads_dir, backup_dir=self.backup_dir)
        manifest_path = result["path"] + ".manifest.json"
        self.assertTrue(os.path.isfile(manifest_path))
        with open(manifest_path) as f:
            manifest = json.loads(f.read())
        self.assertEqual(manifest["backup_type"], "full")


class TestBackupCenterRestoreFull(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "falcon_web.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT)")
        c.execute("INSERT INTO user VALUES (1, 'original')")
        conn.commit()
        conn.close()

        self.uploads_dir = os.path.join(self.tmpdir, "uploads")
        os.makedirs(self.uploads_dir, exist_ok=True)
        with open(os.path.join(self.uploads_dir, "original.txt"), "w") as f:
            f.write("original")

        self.backup_dir = os.path.join(self.tmpdir, "backups")
        self.full_backup = create_full_backup(
            db_path=self.db_path, uploads_dir=self.uploads_dir, backup_dir=self.backup_dir
        )

        conn2 = sqlite3.connect(self.db_path)
        c2 = conn2.cursor()
        c2.execute("DELETE FROM user")
        c2.execute("INSERT INTO user VALUES (2, 'replaced')")
        conn2.commit()
        conn2.close()

        with open(os.path.join(self.uploads_dir, "original.txt"), "w") as f:
            f.write("modified")
        with open(os.path.join(self.uploads_dir, "new.txt"), "w") as f:
            f.write("new")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_restore_full_zip(self):
        result = restore_backup_full(self.full_backup["path"], target_db_path=self.db_path, uploads_dir=self.uploads_dir)
        self.assertTrue(result["success"])

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT username FROM user WHERE id=1")
        row = c.fetchone()
        self.assertEqual(row[0], "original")
        conn.close()

    def test_restore_full_zip_uploads(self):
        result = restore_backup_full(self.full_backup["path"], target_db_path=self.db_path, uploads_dir=self.uploads_dir)
        self.assertTrue(result["success"])
        upload_path = os.path.join(self.uploads_dir, "original.txt")
        with open(upload_path) as f:
            self.assertEqual(f.read(), "original")

    def test_restore_full_verification(self):
        result = restore_backup_full(self.full_backup["path"], target_db_path=self.db_path, uploads_dir=self.uploads_dir)
        self.assertIn("verification", result)
        self.assertTrue(result["verification"]["all_ok"])

    def test_restore_full_pre_restore_backup(self):
        result = restore_backup_full(self.full_backup["path"], target_db_path=self.db_path, uploads_dir=self.uploads_dir)
        self.assertIn("pre_restore_backup", result)
        self.assertTrue(result["pre_restore_backup"]["success"])

    def test_restore_full_not_found(self):
        result = restore_backup_full("/nonexistent.zip", target_db_path=self.db_path)
        self.assertFalse(result["success"])


class TestBackupCenterVerification(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT)")
        c.execute("INSERT INTO user VALUES (1, 'alice')")
        c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, content TEXT)")
        c.execute("INSERT INTO message VALUES (1, 'hello')")
        c.execute("CREATE TABLE `group` (id INTEGER PRIMARY KEY, name TEXT)")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_verify_restore_ok(self):
        result = verify_restore(self.db_path)
        self.assertTrue(result["all_ok"])
        self.assertTrue(result["integrity"]["ok"])
        self.assertTrue(result["users"]["ok"])
        self.assertTrue(result["messages"]["ok"])
        self.assertTrue(result["groups"]["ok"])

    def test_verify_restore_missing_db(self):
        result = verify_restore("/nonexistent.db")
        self.assertFalse(result["all_ok"])
        self.assertFalse(result["integrity"]["ok"])

    def test_check_db_integrity_ok(self):
        result = _check_db_integrity(self.db_path)
        self.assertTrue(result["ok"])

    def test_check_db_integrity_corrupted(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE x (id INTEGER PRIMARY KEY, data TEXT)")
        c.execute("INSERT INTO x VALUES (1, 'hello')")
        conn.commit()
        conn.close()
        with open(self.db_path, "r+b") as f:
            f.seek(100)
            f.write(b"\x00\x00\x00INVALID")
        result = _check_db_integrity(self.db_path)
        self.assertFalse(result["ok"])

    def test_verify_entity_user_exists(self):
        result = _verify_entity(self.db_path, "user")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_verify_entity_nonexistent_table(self):
        result = _verify_entity(self.db_path, "nonexistent")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["note"], "table not present")

    def test_verify_entity_missing_db(self):
        result = _verify_entity("/nonexistent.db", "user")
        self.assertFalse(result["ok"])


class TestBackupCenterCompatibility(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "current.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        c.execute("CREATE TABLE message (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        self.backup_path = os.path.join(self.tmpdir, "backup.db")
        conn2 = sqlite3.connect(self.backup_path)
        c2 = conn2.cursor()
        c2.execute("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        c2.execute("CREATE TABLE message (id INTEGER PRIMARY KEY)")
        c2.execute("CREATE TABLE `group` (id INTEGER PRIMARY KEY)")
        conn2.commit()
        conn2.close()

        from utils.backup import _write_sha256_sidecar, _sha256_file
        digest = _sha256_file(self.backup_path)
        _write_sha256_sidecar(self.backup_path, digest)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_check_compatibility_ok(self):
        result = check_compatibility(self.backup_path, current_db_path=self.db_path)
        self.assertTrue(result["compatible"])

    def test_check_compatibility_backup_schema(self):
        result = check_compatibility(self.backup_path, current_db_path=self.db_path)
        self.assertEqual(result["backup_schema"], 3)
        self.assertEqual(result["current_schema"], 2)

    def test_check_compatibility_missing_file(self):
        result = check_compatibility("/nonexistent.db", current_db_path=self.db_path)
        self.assertFalse(result["compatible"])

    def test_check_compatibility_zip(self):
        with zipfile.ZipFile(os.path.join(self.tmpdir, "test.zip"), "w") as zf:
            zf.writestr("manifest.json", json.dumps({"database_schema_version": 3}))
        result = check_compatibility(os.path.join(self.tmpdir, "test.zip"), current_db_path=self.db_path)
        self.assertTrue(result["compatible"])

    def test_check_compatibility_zip_no_manifest(self):
        with zipfile.ZipFile(os.path.join(self.tmpdir, "bad.zip"), "w") as zf:
            zf.writestr("something.txt", "data")
        result = check_compatibility(os.path.join(self.tmpdir, "bad.zip"), current_db_path=self.db_path)
        self.assertFalse(result["compatible"])


class TestBackupCenterSearchAndSummary(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "falcon_web.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO user VALUES (1)")
        conn.commit()
        conn.close()

        self.backup_dir = os.path.join(self.tmpdir, "backups")
        self.quick1 = create_quick_backup(db_path=self.db_path, backup_dir=self.backup_dir)
        self.quick2 = create_quick_backup(db_path=self.db_path, backup_dir=self.backup_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_list_backups_new(self):
        backups = list_backups(backup_dir=self.backup_dir)
        self.assertGreaterEqual(len(backups), 2)

    def test_list_backups_by_type(self):
        backups = list_backups(backup_dir=self.backup_dir, backup_type=QUICK_SUBDIR)
        self.assertGreaterEqual(len(backups), 2)

    def test_search_backups(self):
        results = search_backups("falcon", backup_dir=self.backup_dir)
        self.assertGreaterEqual(len(results), 1)

    def test_search_backups_no_match(self):
        results = search_backups("zzz_nonexistent", backup_dir=self.backup_dir)
        self.assertEqual(len(results), 0)

    def test_get_backup_summary(self):
        summary = get_backup_summary(backup_dir=self.backup_dir)
        self.assertGreaterEqual(summary["total"], 2)
        self.assertIn("by_type", summary)
        self.assertIn("total_size_bytes", summary)
        self.assertIn("total_size_mb", summary)


class TestBackupCenterRetention(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "falcon_web.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        c.execute("INSERT INTO user VALUES (1)")
        conn.commit()
        conn.close()

        self.backup_dir = os.path.join(self.tmpdir, "backups")
        for btype in (QUICK_SUBDIR, FULL_SUBDIR):
            dirpath = os.path.join(self.backup_dir, btype)
            os.makedirs(dirpath, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_apply_retention_empty(self):
        result = apply_retention(backup_dir=self.backup_dir)
        self.assertTrue(result["success"])


class TestBackupCenterVerifyBackupFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.filepath = os.path.join(self.tmpdir, "test.db.backup.20260705_120000")
        with open(self.filepath, "wb") as f:
            f.write(b"test data")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_verify_no_sidecar(self):
        result = verify_backup_file(self.filepath)
        self.assertTrue(result["valid"])
        self.assertFalse(result["has_sidecar"])

    def test_verify_with_sidecar(self):
        from utils.backup import _sha256_file, _write_sha256_sidecar
        digest = _sha256_file(self.filepath)
        _write_sha256_sidecar(self.filepath, digest)
        result = verify_backup_file(self.filepath)
        self.assertTrue(result["valid"])
        self.assertTrue(result["has_sidecar"])
        self.assertTrue(result["match"])

    def test_verify_mismatched_sidecar(self):
        from utils.backup import _write_sha256_sidecar
        _write_sha256_sidecar(self.filepath, "00000000" * 8)
        result = verify_backup_file(self.filepath)
        self.assertFalse(result["valid"])
        self.assertFalse(result["match"])

    def test_verify_missing_file(self):
        result = verify_backup_file("/nonexistent")
        self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
