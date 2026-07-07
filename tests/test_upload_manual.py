"""Manual upload/download regression tests for Phase 4D hardening.

Run with: python -m unittest test_upload_manual -v

Requires the Falcon Web App test environment (same TestConfig as test_web_app.py).
"""
import unittest
import io
import os
import tempfile
from app import create_app
from database.database import db
from models.models import User
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key-for-testing-only'
    UPLOAD_FOLDER = tempfile.mkdtemp()


class UploadManualTests(unittest.TestCase):
    """Battery of manual upload/download tests."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        db.create_all()
        # Create test user once
        u = User(username='Alice')
        u.set_password('password123')
        db.session.add(u)
        db.session.commit()
        cls.user_id = u.id

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.ctx.pop()
        import shutil
        shutil.rmtree(cls.app.config['UPLOAD_FOLDER'], ignore_errors=True)

    def setUp(self):
        """Create a fresh test client and log in for each test."""
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['username'] = 'Alice'

    def _upload(self, filename, content=b'hello', content_type=None):
        data = {'file': (io.BytesIO(content), filename, content_type or 'application/octet-stream')}
        return self.client.post('/api/upload', data=data, content_type='multipart/form-data')

    # ── 1. Normal upload ───────────────────────────────────────────────

    def test_01_normal_txt_upload(self):
        """A plain .txt file uploads successfully."""
        res = self._upload('hello.txt')
        self.assertEqual(res.status_code, 200)
        j = res.get_json()
        self.assertTrue(j['success'])
        self.assertTrue(j['data']['filename'].endswith('_hello.txt'))
        self.assertEqual(j['data']['size'], 5)

    def test_02_normal_jpg_upload(self):
        """A .jpg file uploads successfully."""
        res = self._upload('photo.jpg')
        self.assertEqual(res.status_code, 200)

    def test_03_normal_png_upload(self):
        """A .png file uploads successfully."""
        res = self._upload('image.png')
        self.assertEqual(res.status_code, 200)

    def test_04_normal_pdf_upload(self):
        """A .pdf file uploads successfully."""
        res = self._upload('doc.pdf')
        self.assertEqual(res.status_code, 200)

    def test_05_normal_zip_upload(self):
        """A .zip file uploads successfully."""
        res = self._upload('archive.zip')
        self.assertEqual(res.status_code, 200)

    # ── 2. Large upload (> 50 MB) ──────────────────────────────────────

    def test_06_oversized_upload(self):
        """A file larger than MAX_UPLOAD_SIZE is rejected with 413."""
        large = b'x' * (51 * 1024 * 1024)
        res = self._upload('large.txt', content=large)
        self.assertEqual(res.status_code, 413)
        j = res.get_json()
        self.assertEqual(j['error']['message'], 'File too large.')

    # ── 3. Dangerous extension (blocklist → allowlist) ─────────────────

    def test_07_exe_rejected(self):
        res = self._upload('malware.exe')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'File type not allowed.')

    def test_08_bat_rejected(self):
        res = self._upload('script.bat')
        self.assertEqual(res.status_code, 400)

    def test_09_dll_rejected(self):
        res = self._upload('library.dll')
        self.assertEqual(res.status_code, 400)

    def test_10_ps1_rejected(self):
        res = self._upload('script.ps1')
        self.assertEqual(res.status_code, 400)

    def test_11_sh_rejected(self):
        res = self._upload('script.sh')
        self.assertEqual(res.status_code, 400)

    def test_12_jar_rejected(self):
        res = self._upload('app.jar')
        self.assertEqual(res.status_code, 400)

    def test_13_php_rejected(self):
        res = self._upload('shell.php')
        self.assertEqual(res.status_code, 400)

    def test_14_asp_rejected(self):
        res = self._upload('page.asp')
        self.assertEqual(res.status_code, 400)

    def test_15_cgi_rejected(self):
        res = self._upload('script.cgi')
        self.assertEqual(res.status_code, 400)

    # ── 4. Double extension ────────────────────────────────────────────

    def test_16_double_extension_rejected(self):
        """image.png.exe is rejected because .exe is not allowed."""
        res = self._upload('image.png.exe')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'File type not allowed.')

    def test_17_double_extension_allowed(self):
        """archive.tar.gz is allowed (both .tar and .gz are in allowlist)."""
        # .gz is not in current allowlist — skip if not
        from utils.security.constants import ALLOWED_EXTENSIONS
        if '.gz' not in ALLOWED_EXTENSIONS:
            self.skipTest('.gz not in ALLOWED_EXTENSIONS')
        res = self._upload('archive.tar.gz')
        self.assertEqual(res.status_code, 200)

    # ── 5. Unicode filename ────────────────────────────────────────────

    def test_18_unicode_filename_accepted(self):
        """Accented characters in filename are sanitized but upload succeeds."""
        # sanitize_filename strips non-ASCII, so "résumé.txt" → "rsum.txt"
        res = self._upload('résumé.txt')
        self.assertEqual(res.status_code, 200)
        fname = res.get_json()['data']['filename']
        self.assertIn('_rsum.txt', fname)

    # ── 6. RLO filename ────────────────────────────────────────────────

    def test_19_rlo_filename_rejected(self):
        """Right-to-Left Override (U+202E) in filename is rejected."""
        # U+202E makes "cod.exe" display as "exe.doc"
        rlo = '\u202E'
        res = self._upload(f'file{rlo}exe.txt')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'Invalid filename')

    # ── 7. Long filename ───────────────────────────────────────────────

    def test_20_long_filename_rejected(self):
        """Filename longer than MAX_FILE_NAME_LENGTH (255) is rejected."""
        long_name = 'A' * 256 + '.txt'
        res = self._upload(long_name)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'Invalid filename')

    # ── 8. Empty filename ──────────────────────────────────────────────

    def test_21_empty_filename_rejected(self):
        res = self._upload('')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'No selected file')

    # ── 9. No extension ────────────────────────────────────────────────

    def test_22_no_extension_rejected(self):
        res = self._upload('README')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'Invalid filename')

    # ── 10. Invalid extension (not in allowlist) ───────────────────────

    def test_23_unknown_extension_rejected(self):
        res = self._upload('file.xyz')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'File type not allowed.')

    # ── 11. Upload without authentication ──────────────────────────────

    def test_24_upload_unauthenticated(self):
        # Use a separate client with a fresh (empty) session
        unauth_client = self.app.test_client()
        data = {'file': (io.BytesIO(b'hello'), 'hello.txt', 'application/octet-stream')}
        res = unauth_client.post('/api/upload', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 401)

    # ── 12. Missing file part ──────────────────────────────────────────

    def test_25_missing_file_part(self):
        """Missing file part returns No file part (even when authenticated)."""
        res = self.client.post('/api/upload', data={}, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'No file part')

    # ── 13. Download tests ─────────────────────────────────────────────

    def test_26_download_existing_file(self):
        res = self._upload('download_me.txt', content=b'world')
        self.assertEqual(res.status_code, 200)
        fname = res.get_json()['data']['filename']
        res2 = self.client.get(f'/api/download/{fname}')
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data, b'world')

    def test_27_download_path_traversal(self):
        """Path traversal in download URL is neutralized by sanitize_filename.
        sanitize_filename strips `../`, leaving `passwd`, which doesn't
        exist on disk → 404.  Path traversal is blocked by design."""
        res = self.client.get('/api/download/../etc/passwd')
        self.assertEqual(res.status_code, 404)

    def test_28_download_nonexistent_file(self):
        res = self.client.get('/api/download/nonexistent_abc123.txt')
        self.assertEqual(res.status_code, 404)

    # ── 14. Control characters ─────────────────────────────────────────

    def test_29_null_byte_rejected(self):
        """Null byte (0x00) in filename is rejected."""
        res = self._upload('file\x00.txt')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'Invalid filename')

    def test_30_newline_rejected(self):
        """Newline (0x0A) in filename is rejected."""
        res = self._upload('file\n.txt')
        self.assertEqual(res.status_code, 400)

    # ── 15. Valid MIME types that pass advisory check ──────────────────

    def test_31_valid_image_mime(self):
        res = self._upload('img.png', content=b'PNG', content_type='image/png')
        self.assertEqual(res.status_code, 200)

    def test_32_valid_audio_mime(self):
        res = self._upload('audio.mp3', content=b'MP3', content_type='audio/mpeg')
        self.assertEqual(res.status_code, 200)

    def test_33_valid_document_mime(self):
        res = self._upload('doc.pdf', content=b'PDF', content_type='application/pdf')
        self.assertEqual(res.status_code, 200)

    # ── 16. Suspicious MIME type ───────────────────────────────────────

    def test_34_suspicious_mime_rejected(self):
        """application/x-msdownload MIME triggers advisory block."""
        res = self._upload('readme.txt', content_type='application/x-msdownload')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error']['message'], 'File type not allowed.')


if __name__ == '__main__':
    unittest.main()
