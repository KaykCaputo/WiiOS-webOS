import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('session', ROOT / 'session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


class GeneratedBundleValidation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bundle = Path(temporary.name)
        for name in session.PAYLOAD:
            (self.bundle / name).write_text('synthetic test payload: ' + name + '\n')
        self.manifest = {
            'token': 'diag-test01',
            'base': '/var/lib/webosbrew/wiios-fullhome-diag/diag-test01',
            'kind': 'diagnostic-only',
            'files': [
                {'name': name,
                 'patched_sha256': hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()}
                for name in ('main.qml', 'UIController.qml')
            ],
        }
        self.save_manifest()

    def save_manifest(self):
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_complete_diagnostic_bundle_is_accepted(self):
        self.assertEqual(session.load_bundle(self.bundle), self.manifest)

    def test_redirect_trial_bundle_is_accepted(self):
        self.manifest['kind'] = 'redirect-trial'
        self.save_manifest()
        self.assertEqual(session.load_bundle(self.bundle), self.manifest)

    def test_corrupt_qml_is_rejected(self):
        (self.bundle / 'main.qml').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            session.load_bundle(self.bundle)

    def test_missing_rollback_is_rejected(self):
        (self.bundle / 'rollback.sh').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing/unsafe file'):
            session.load_bundle(self.bundle)

    def test_symlink_payload_is_rejected(self):
        (self.bundle / 'watchdog.sh').unlink()
        (self.bundle / 'watchdog.sh').symlink_to(self.bundle / 'status.sh')
        with self.assertRaisesRegex(ValueError, 'Missing/unsafe file'):
            session.load_bundle(self.bundle)

    def test_untrusted_base_is_rejected(self):
        self.manifest['base'] = '/tmp/outside-sandbox'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Invalid remote path'):
            session.load_bundle(self.bundle)

    def test_invalid_token_is_rejected(self):
        self.manifest['token'] = 'diag-;id'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Invalid token'):
            session.load_bundle(self.bundle)


if __name__ == '__main__':
    unittest.main()
