import hashlib
import json
import unittest

from home.manifest import staged_web_home
from installer.errors import InstallerError


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.original = json.dumps({'id': 'com.webos.app.home', 'type': 'flutter',
            'main': 'old.exe', 'appCategory': ['home', 'system'], 'extra': 'preserved'}, sort_keys=True).encode()
        self.sha256 = hashlib.sha256(self.original).hexdigest()

    def test_preserves_original_identity_category_and_metadata(self):
        staged = staged_web_home(self.original, self.sha256)
        info = json.loads(staged['content'])
        self.assertEqual(info['id'], 'com.webos.app.home')
        self.assertEqual(info['appCategory'], ['home', 'system'])
        self.assertEqual(info['main'], 'index.html')
        self.assertEqual(info['type'], 'web')
        self.assertEqual(info['extra'], 'preserved')
        self.assertFalse(info['visible'])
        self.assertEqual(staged['sha256'], hashlib.sha256(staged['content']).hexdigest())

    def test_rejects_changed_original_or_arbitrary_app(self):
        for original, fingerprint in [
            (self.original + b' ', self.sha256),
            (json.dumps({'id': 'com.wiios.launcher', 'type': 'web', 'appCategory': ['home']}).encode(),
             hashlib.sha256(json.dumps({'id': 'com.wiios.launcher', 'type': 'web', 'appCategory': ['home']}).encode()).hexdigest()),
            (json.dumps({'id': 'com.webos.app.home', 'type': 'web', 'appCategory': []}).encode(),
             hashlib.sha256(json.dumps({'id': 'com.webos.app.home', 'type': 'web', 'appCategory': []}).encode()).hexdigest())
        ]:
            with self.assertRaises(InstallerError):
                staged_web_home(original, fingerprint)

    def test_rejects_path_traversal(self):
        with self.assertRaises(InstallerError):
            staged_web_home(self.original, self.sha256, '../index.html')
