import unittest
import os
import json
import tempfile
import shutil
import hashlib
from utils.migration.printer import generate_report, print_summary, save_report, format_human_readable, sha256_checksum


SAMPLE_PROGRESS = {
    "import_id": "IMP-20240704-ABCD",
    "status": "completed",
    "progress_pct": 100,
    "tables": {
        "user": {"status": "completed", "current": 3, "total": 3, "error": None},
        "message": {"status": "completed", "current": 2, "total": 2, "error": None},
        "group": {"status": "skipped", "current": 0, "total": 0, "error": None},
        "group_member": {"status": "completed", "current": 2, "total": 2, "error": None},
        "group_invite": {"status": "completed", "current": 1, "total": 1, "error": None},
        "group_join_request": {"status": "completed", "current": 1, "total": 1, "error": None},
        "system_broadcast": {"status": "completed", "current": 1, "total": 1, "error": None},
    },
    "error": None,
    "results": {
        "user": {"imported": 3, "skipped": 0, "replaced": 0, "total": 3},
        "message": {"imported": 2, "skipped": 0, "replaced": 0, "total": 2},
        "group": {"imported": 0, "skipped": 0, "replaced": 0, "total": 0},
        "group_member": {"imported": 2, "skipped": 0, "replaced": 0, "total": 2},
        "group_invite": {"imported": 1, "skipped": 0, "replaced": 0, "total": 1},
        "group_join_request": {"imported": 1, "skipped": 0, "replaced": 0, "total": 1},
        "system_broadcast": {"imported": 1, "skipped": 0, "replaced": 0, "total": 1},
    },
}

FAILED_PROGRESS = {
    "import_id": "IMP-20240704-EFGH",
    "status": "failed",
    "progress_pct": 50,
    "tables": {
        "user": {"status": "completed", "current": 3, "total": 3, "error": None},
        "message": {"status": "failed", "current": 1, "total": 2, "error": "IntegrityError at batch 0"},
    },
    "error": "Import failed for message batch #0: UNIQUE constraint failed",
    "results": {
        "user": {"imported": 3, "skipped": 0, "replaced": 0, "total": 3},
    },
}


class TestSha256Checksum(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_sha256_nonexistent(self):
        self.assertIsNone(sha256_checksum(os.path.join(self.tmpdir, "nonexistent")))

    def test_sha256_known_value(self):
        path = os.path.join(self.tmpdir, "test.bin")
        with open(path, "wb") as f:
            f.write(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        self.assertEqual(sha256_checksum(path), expected)

    def test_sha256_empty_file(self):
        path = os.path.join(self.tmpdir, "empty.bin")
        with open(path, "wb") as f:
            pass
        expected = hashlib.sha256(b"").hexdigest()
        self.assertEqual(sha256_checksum(path), expected)


class TestGenerateReport(unittest.TestCase):
    def test_generate_report_basic(self):
        report = generate_report(SAMPLE_PROGRESS)
        self.assertEqual(report["import_id"], "IMP-20240704-ABCD")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["progress_pct"], 100)
        self.assertIn("import_summary", report)

    def test_generate_report_summary_counts(self):
        report = generate_report(SAMPLE_PROGRESS)
        summary = report["import_summary"]
        self.assertEqual(summary["total_imported"], 10)
        self.assertEqual(summary["total_skipped"], 0)
        self.assertEqual(summary["total_records"], 10)

    def test_generate_report_with_scan_and_validation(self):
        scan = {"version": "v1", "total_rows": 10}
        validation = {"issues": [], "valid": True}
        report = generate_report(SAMPLE_PROGRESS, scan_result=scan, validation_result=validation)
        self.assertIn("scan", report)
        self.assertIn("validation", report)

    def test_generate_report_failed(self):
        report = generate_report(FAILED_PROGRESS)
        self.assertEqual(report["status"], "failed")
        self.assertIsNotNone(report["error"])

    def test_generate_report_tables(self):
        report = generate_report(SAMPLE_PROGRESS)
        self.assertIn("user", report["tables"])
        self.assertEqual(report["tables"]["user"]["status"], "completed")
        self.assertEqual(report["tables"]["user"]["total"], 3)

    def test_generate_report_with_sha256(self):
        report = generate_report(SAMPLE_PROGRESS, imported_db_path=None)
        self.assertNotIn("sha256", report)

    def test_generate_report_with_backup(self):
        progress = dict(SAMPLE_PROGRESS)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.write(b"test")
        tmp.close()
        progress["pre_import_backup"] = {"path": tmp.name}
        try:
            report = generate_report(progress)
            self.assertIn("pre_import_backup", report)
            self.assertIn("sha256", report["pre_import_backup"])
            self.assertEqual(report["pre_import_backup"]["path"], tmp.name)
        finally:
            os.unlink(tmp.name)


class TestPrintSummary(unittest.TestCase):
    def test_print_summary_output(self):
        import io
        buf = io.StringIO()
        result = print_summary(SAMPLE_PROGRESS, output=buf)
        output = buf.getvalue()
        self.assertIn("Import ID: IMP-20240704-ABCD", output)
        self.assertIn("Status: completed", output)
        self.assertIn("user", output)
        self.assertIn("message", output)

    def test_print_summary_failed(self):
        import io
        buf = io.StringIO()
        result = print_summary(FAILED_PROGRESS, output=buf)
        output = buf.getvalue()
        self.assertIn("Status: failed", output)
        self.assertIn("Error:", output)

    def test_print_summary_returns_string(self):
        import io
        buf = io.StringIO()
        result = print_summary(SAMPLE_PROGRESS, output=buf)
        self.assertIn("Import ID:", result)

    def test_format_human_readable_alias(self):
        self.assertIs(format_human_readable, print_summary)

    def test_print_summary_with_sha256(self):
        import io
        progress = dict(SAMPLE_PROGRESS)
        progress["sha256"] = "abc123"
        buf = io.StringIO()
        print_summary(progress, output=buf)
        output = buf.getvalue()
        self.assertIn("SHA256: abc123", output)


class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_save_report_creates_files_in_subdir(self):
        paths = save_report(SAMPLE_PROGRESS, log_dir=self.tmpdir)
        self.assertTrue(os.path.isfile(paths["report_path"]))
        self.assertTrue(os.path.isfile(paths["summary_path"]))
        import_id = SAMPLE_PROGRESS["import_id"]
        expected_dir = os.path.join(self.tmpdir, import_id)
        self.assertEqual(os.path.dirname(paths["report_path"]), expected_dir)

    def test_save_report_json_content(self):
        paths = save_report(SAMPLE_PROGRESS, log_dir=self.tmpdir)
        with open(paths["report_path"], "r") as f:
            data = json.load(f)
        self.assertEqual(data["import_id"], "IMP-20240704-ABCD")
        self.assertEqual(data["status"], "completed")

    def test_save_report_with_scan_and_validation(self):
        scan = {"version": "v1", "total_rows": 10}
        validation = {"issues": [], "valid": True}
        paths = save_report(SAMPLE_PROGRESS, log_dir=self.tmpdir, scan_result=scan, validation_result=validation)
        with open(paths["report_path"], "r") as f:
            data = json.load(f)
        self.assertIn("scan", data)
        self.assertIn("validation", data)

    def test_save_report_creates_dir(self):
        nested = os.path.join(self.tmpdir, "nested", "imports")
        paths = save_report(SAMPLE_PROGRESS, log_dir=nested)
        self.assertTrue(os.path.isdir(paths["report_dir"]))
        self.assertTrue(os.path.isfile(paths["report_path"]))

    def test_save_report_with_sha256_in_report(self):
        db_path = os.path.join(self.tmpdir, "test.db")
        with open(db_path, "wb") as f:
            f.write(b"test database content")
        paths = save_report(SAMPLE_PROGRESS, log_dir=self.tmpdir, imported_db_path=db_path)
        with open(paths["report_path"], "r") as f:
            data = json.load(f)
        self.assertIn("sha256", data)
        expected = hashlib.sha256(b"test database content").hexdigest()
        self.assertEqual(data["sha256"], expected)

    def test_save_report_filenames(self):
        paths = save_report(SAMPLE_PROGRESS, log_dir=self.tmpdir)
        self.assertTrue(paths["report_path"].endswith("report.json"))
        self.assertTrue(paths["summary_path"].endswith("report.txt"))


if __name__ == "__main__":
    unittest.main()
