from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from installer.install_engine import InstallEngine
from installer.journal import Journal


class HostRecoveryIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ident = 'a' * 64
        self.missing_bundle = self.root / 'deleted-staging-directory'
        self.plan = {'transactionId': self.ident, 'mode': 'home-replacement', 'adapter': 'home-directory-takeover'}
        self.profile = {'home': {'appId': 'com.webos.app.home'}}
        self.transport = SimpleNamespace(connection=SimpleNamespace(endpoint='root@tv:22'))
        self.journal = Journal(self.root / 'journals')
        self.engine = InstallEngine(self.transport, self.journal)
        self.host = {'schemaVersion': 1, 'transactionId': self.ident, 'plan': self.plan,
                     'profile': self.profile, 'bundleManifest': {'files': {'index.html': 'b' * 64}},
                     'bundleDirectory': str(self.missing_bundle), 'samProtocol': 'sam-block-release-v1',
                     'endpoint': self.transport.connection.endpoint, 'state': 'TRIAL_ACTIVE'}
        self.journal.save(self.host)

    @patch('home.operations.device_backend.DeviceHomeBackend')
    def test_host_restore_uses_device_journal_without_local_bundle(self, backend_type):
        backend = backend_type.return_value
        backend.read_device_journal.return_value = {'transactionId': self.ident, 'plan': self.plan,
                                                      'state': 'TRIAL_ACTIVE', 'events': []}
        backend.verify_stock_files.return_value = True
        backend.verify_stock.return_value = False
        self.assertFalse(self.missing_bundle.exists())
        restored = self.engine.home_trial_state(self.ident, 'restore')
        self.assertTrue(restored['ok'])
        self.assertFalse(restored['stockHomeVerified'])
        self.assertEqual(restored['state'], 'STOCK_FILES_RESTORED')
        self.assertEqual(self.journal.read(self.ident)['state'], 'STOCK_FILES_RESTORED')
        backend_type.assert_called_once()

    @patch('home.operations.device_backend.DeviceHomeBackend')
    def test_lost_staging_does_not_turn_file_hash_into_stock_home_confirmation(self, backend_type):
        backend = backend_type.return_value
        backend.read_device_journal.return_value = {'transactionId': self.ident, 'plan': self.plan,
                                                      'state': 'STOCK_FILES_RESTORED', 'events': []}
        backend.verify_stock_files.return_value = True
        backend.verify_stock.return_value = False
        result = self.engine.home_trial_state(self.ident, 'restore')
        self.assertEqual(result['state'], 'STOCK_FILES_RESTORED')
        self.assertFalse(result['stockHomeVerified'])


class DeviceJournalRecoveryTests(unittest.TestCase):
    def test_missing_host_journal_is_reconstructed_from_verified_device_metadata(self):
        from compatibility.tests.fixtures import profile
        from home.adapters.qml_redirect import QmlRedirect
        import json
        with tempfile.TemporaryDirectory() as directory:
            original = profile()
            plan = QmlRedirect().build_plan(original)
            transaction_id = plan['transactionId']
            remote = {'transactionId': transaction_id, 'plan': plan, 'state': 'TRIAL_ACTIVE',
                      'recoveryMetadata': {'profile': original, 'bundleManifest': {'files': {}},
                                           'samProtocol': None, 'nativeContract': None,
                                           'launchPayload': None}}
            transport = SimpleNamespace(kind='root-ssh',
                connection=SimpleNamespace(endpoint='root@tv:22'),
                execute=Mock(side_effect=lambda command: '0' if command == 'id -u' else json.dumps(remote)),
                luna=Mock(return_value={'returnValue': True,
                    'modelName': original['identity']['model'], 'boardType': original['identity']['board']}))
            journal = Journal(Path(directory) / 'journals')
            engine = InstallEngine(transport, journal)
            engine.import_device_recovery(transaction_id)
            restored = journal.read(transaction_id)
            self.assertEqual(restored['plan'], plan)
            self.assertEqual(restored['bundleDirectory'], '.')
            self.assertEqual(restored['state'], 'TRIAL_ACTIVE')
