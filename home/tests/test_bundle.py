import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from home.bundle import prepare_web_home, verify_web_home
from installer.errors import InstallerError


class WebHomeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        (self.app / 'appinfo.json').write_text(json.dumps({'id': 'com.wiios.launcher', 'version': '0.3.35'}))
        for name in ('index.html', 'app.js', 'bridge.js', 'style.css'):
            (self.app / name).write_text(name)
        self.stock = json.dumps({'id': 'com.webos.app.home', 'type': 'flutter',
                                 'appCategory': ['home', 'other'], 'main': 'index.html'}).encode()
        self.digest = hashlib.sha256(self.stock).hexdigest()
        self.target = self.root / 'staged'

    def build(self):
        return prepare_web_home(self.app, self.stock, self.digest, self.target)

    def test_build_preserves_home_identity_and_checks_every_asset(self):
        result = self.build()
        self.assertEqual(result['homeAppId'], 'com.webos.app.home')
        self.assertTrue(verify_web_home(self.target, result))
        candidate = json.loads((self.target / 'appinfo.json').read_text())
        self.assertEqual(candidate['type'], 'web')
        self.assertIn('home', candidate['appCategory'])
        self.assertFalse(candidate['visible'])

    def test_modified_stock_manifest_is_rejected_before_writing(self):
        with self.assertRaises(InstallerError):
            prepare_web_home(self.app, self.stock + b' ', self.digest, self.target)
        self.assertFalse(self.target.exists())

    def test_symlinked_asset_is_rejected_without_writing(self):
        (self.app / 'external.js').symlink_to(self.root / 'nonexistent')
        with self.assertRaises(InstallerError):
            self.build()
        self.assertFalse(self.target.exists())

    def test_changed_asset_is_detected_after_staging(self):
        manifest = self.build()
        (self.target / 'app.js').write_text('changed')
        with self.assertRaises(InstallerError):
            verify_web_home(self.target, manifest)

    def test_unknown_app_cannot_be_disguised_as_wiios(self):
        (self.app / 'appinfo.json').write_text(json.dumps({'id': 'com.example.evil', 'version': '0.3.35'}))
        with self.assertRaises(InstallerError):
            self.build()

    def test_existing_bundle_is_never_overwritten(self):
        self.target.mkdir()
        with self.assertRaises(InstallerError):
            self.build()
