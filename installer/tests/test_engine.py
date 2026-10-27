from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from compatibility.tests.fixtures import profile
from installer.application import Artifact
from installer.errors import InstallerError
from installer.install_engine import InstallEngine
from installer.journal import Journal
from installer.plan import seal_plan
from installer.tui import run
from installer.tui import configure_connection
from scripts.build import build


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = tempfile.TemporaryDirectory()
        with redirect_stdout(io.StringIO()):
            cls.artifact = Artifact(build(output=cls.release.name))

    @classmethod
    def tearDownClass(cls):
        cls.release.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.device = profile()
        self.device['transport'].update(kind='developer-mode', root=False)
        self.application = Mock()
        self.application.install.return_value = {'ok': True, 'state': 'APP_INSTALLED', 'uiConfirmed': False}
        transport = SimpleNamespace(connection=SimpleNamespace(endpoint=self.device['transport']['endpoint']), kind='developer-mode')
        self.engine = InstallEngine(transport, Journal(self.directory.name), self.artifact,
                                    probe_device=lambda transport: deepcopy(self.device), application=self.application)

    def test_ht19_app_only_calls_only_application_installer(self):
        plan = self.engine.plan(mode='app')
        self.assertFalse(plan['requiresRoot'])
        self.assertIsNone(plan['adapter'])
        self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual([call[0] for call in self.application.mock_calls], ['install'])
        self.assertEqual(self.engine.journal.read(plan['transactionId'])['state'], 'COMMITTED')

    def test_ht20_tui_uses_identical_engine_plan_and_approval(self):
        plan = self.engine.plan(mode='app')
        answers = iter(['1', plan['approvalDigest'], '0'])
        output = []
        run(self.engine, read=lambda prompt: next(answers), write=output.append)
        self.assertTrue(any(plan['approvalDigest'] in text for text in output))
        self.application.install.assert_called_once_with(self.artifact, plan['transactionId'])

    def test_tui_cancel_has_no_mutation(self):
        answers = iter(['1', '', '0'])
        run(self.engine, read=lambda prompt: next(answers), write=lambda text: None)
        self.application.install.assert_not_called()

    def test_tui_collects_connection_without_assuming_root_or_port(self):
        args = SimpleNamespace(host=None, port=None, user=None, identity=None, transport='developer-mode')
        answers = iter(['1', '192.0.2.1', '9922', 'prisoner', ''])
        configure_connection(args, read=lambda prompt: next(answers), write=lambda text: None)
        self.assertEqual((args.transport, args.port, args.user), ('developer-mode', 9922, 'prisoner'))

    def test_retry_after_commit_is_idempotent_and_journal_is_preserved(self):
        plan = self.engine.plan(mode='app')
        self.application.version.return_value = self.artifact.version
        first = self.engine.apply(plan, plan['approvalDigest'])
        second = self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual(first['transactionId'], second['transactionId'])
        self.assertTrue(second['alreadyApplied'])
        self.application.install.assert_called_once()
        self.assertEqual(self.engine.journal.read(plan['transactionId'])['state'], 'COMMITTED')

    def test_retry_incomplete_transaction_refused_without_overwrite(self):
        plan = self.engine.plan(mode='app')
        self.application.install.side_effect = InstallerError('TRANSPORT_TIMEOUT', 'Disconnected.', 4)
        with self.assertRaises(InstallerError):
            self.engine.apply(plan, plan['approvalDigest'])
        before = self.engine.journal.read(plan['transactionId'])
        with self.assertRaises(InstallerError) as raised:
            self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual(raised.exception.code, 'TRANSACTION_RECONCILIATION_REQUIRED')
        self.assertEqual(self.engine.journal.read(plan['transactionId']), before)
        self.application.install.assert_called_once()

    def test_verified_reconciliation_commits_after_transport_failure(self):
        plan = self.engine.plan(mode='app')
        self.application.install.side_effect = InstallerError('TRANSPORT_TIMEOUT', 'Disconnected.', 4)
        with self.assertRaises(InstallerError):
            self.engine.apply(plan, plan['approvalDigest'])
        self.application.version.return_value = self.artifact.version
        result = self.engine.reconcile_transaction(plan['transactionId'])
        self.assertTrue(result['reconciled'])
        self.assertFalse(result['uiConfirmed'])
        self.assertEqual(self.engine.journal.read(plan['transactionId'])['state'], 'COMMITTED')
        self.assertEqual(self.engine.reconcile(), [])

    def test_unconfirmed_reconciliation_preserves_journal(self):
        plan = self.engine.plan(mode='app')
        self.application.install.side_effect = InstallerError('TRANSPORT_TIMEOUT', 'Disconnected.', 4)
        with self.assertRaises(InstallerError):
            self.engine.apply(plan, plan['approvalDigest'])
        self.application.version.return_value = '0.0.1'
        result = self.engine.reconcile_transaction(plan['transactionId'])
        self.assertEqual(result['reasonCode'], 'APP_VERSION_NOT_CONFIRMED')
        self.assertEqual(self.engine.journal.read(plan['transactionId'])['state'], 'RECONCILE_REQUIRED')

    def test_reconciliation_refuses_changed_firmware_and_host(self):
        plan = self.engine.plan(mode='app')
        self.application.install.side_effect = InstallerError('TRANSPORT_TIMEOUT', 'Disconnected.', 4)
        with self.assertRaises(InstallerError):
            self.engine.apply(plan, plan['approvalDigest'])
        self.device['identity']['firmware'] = 'new-firmware'
        with self.assertRaises(InstallerError) as raised:
            self.engine.reconcile_transaction(plan['transactionId'])
        self.assertEqual(raised.exception.code, 'DEVICE_STATE_CHANGED')
        self.device['identity']['firmware'] = profile()['identity']['firmware']
        self.engine.transport.connection.endpoint = 'root@192.0.2.254:22'
        with self.assertRaises(InstallerError) as raised:
            self.engine.reconcile_transaction(plan['transactionId'])
        self.assertEqual(raised.exception.code, 'TRANSACTION_DEVICE_MISMATCH')

    def test_ht21_approved_device_state_change_rejected(self):
        plan = self.engine.plan(mode='app')
        self.device['identity']['firmware'] = 'changed'
        with self.assertRaises(InstallerError) as raised:
            self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual(raised.exception.exit_code, 8)
        self.application.install.assert_not_called()

    def test_resealed_plan_cannot_smuggle_operations(self):
        plan = self.engine.plan(mode='app')
        plan['operations'].append({'action': 'mount-home', 'target': '/usr'})
        plan = seal_plan(plan)
        with self.assertRaises(InstallerError):
            self.engine.apply(plan, plan['approvalDigest'])
        self.application.install.assert_not_called()

    def test_ht13_connection_failure_keeps_recoverable_journal(self):
        plan = self.engine.plan(mode='app')
        self.application.install.side_effect = InstallerError('TRANSPORT_TIMEOUT', 'Disconnected.', 4)
        with self.assertRaises(InstallerError):
            self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual(self.engine.journal.read(plan['transactionId'])['state'], 'RECONCILE_REQUIRED')
        self.assertEqual(len(self.engine.reconcile()), 1)

    def test_ht32_new_engine_discovers_pending_transaction(self):
        plan = self.engine.plan(mode='app')
        self.application.install.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.engine.apply(plan, plan['approvalDigest'])
        fresh = InstallEngine(self.engine.transport, Journal(self.directory.name), self.artifact)
        self.assertEqual(fresh.reconcile()[0]['transactionId'], plan['transactionId'])

    def test_ht23_root_uninstall_rejects_active_home_hook(self):
        self.device['transport']['kind'] = 'root-ssh'
        self.device['home']['conflictingHooks'] = ['99-wiios-fullhome']
        with self.assertRaises(InstallerError) as raised:
            self.engine.uninstall()
        self.assertEqual(raised.exception.exit_code, 7)
        self.application.uninstall.assert_not_called()

    def test_home_unqualified_cannot_be_forced_by_digest(self):
        with self.assertRaises(InstallerError) as raised:
            self.engine.plan(mode='home')
        self.assertEqual(raised.exception.exit_code, 3)

    def test_app_restore_needs_no_plan_digest_and_does_not_uninstall(self):
        plan = self.engine.plan(mode='app')
        self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual(self.engine.restore(plan['transactionId'])['reasonCode'], 'APP_ONLY_HOME_UNCHANGED')
        self.application.uninstall.assert_not_called()

    def test_journal_rejects_path_traversal(self):
        with self.assertRaises(InstallerError):
            self.engine.journal.read('../unrelated')

    def test_artifact_rejects_corrupt_file(self):
        invalid = Path(self.directory.name) / 'invalid.ipk'
        invalid.write_bytes(b'not a package')
        with self.assertRaises(InstallerError):
            Artifact(invalid)
