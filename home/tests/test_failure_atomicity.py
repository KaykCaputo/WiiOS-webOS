import unittest

from compatibility.tests.fixtures import profile
from home.adapters.qml_redirect import QmlRedirect
from home.operations.transaction import HomeTransaction
from home.tests.test_transactions import SimulatedDevice
from installer.errors import InstallerError
from installer.plan import fresh_trial


class RecoveryAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.backend = SimulatedDevice()
        self.plan = QmlRedirect().build_plan(profile())
        self.transaction = HomeTransaction(self.plan, self.backend)

    def test_staging_integrity_failure_restores_staged_payload(self):
        self.backend.integrity = lambda plan: False
        with self.assertRaises(InstallerError):
            self.transaction.stage()
        self.assertEqual(self.backend.journal['state'], 'RESTORED')
        self.assertFalse(self.backend.active)

    def test_watchdog_arm_failure_does_not_leave_a_transaction_active(self):
        self.transaction.stage()
        self.backend.fail_action = 'arm-independent-watchdog'
        with self.assertRaises(InstallerError):
            self.transaction.activate()
        self.assertEqual(self.backend.journal['state'], 'RESTORED')
        self.assertFalse(self.backend.active)

    def test_health_transport_error_rolls_back(self):
        self.transaction.stage()
        self.transaction.activate()
        def fail(plan):
            raise InstallerError('OFFLINE', 'Device unavailable.', 5)
        self.backend.health = fail
        with self.assertRaises(InstallerError):
            self.transaction.verify()
        self.assertEqual(self.backend.journal['state'], 'RESTORED')

    def test_commit_boot_failure_rolls_back_hooks(self):
        self.transaction.stage()
        self.transaction.activate()
        self.transaction.verify()
        self.transaction.restore()
        proof = self.transaction.restoration_proof()
        plan = fresh_trial(self.plan, 'd' * 32)
        next_transaction = HomeTransaction(plan, self.backend)
        next_transaction.stage()
        next_transaction.activate()
        next_transaction.verify()
        next_transaction.commit(proof, plan['approvalDigest'])
        self.backend.boot_id = 'next-boot'
        self.backend.health_result['H4'] = False
        with self.assertRaises(InstallerError):
            next_transaction.finalize()
        self.assertEqual(self.backend.journal['state'], 'RESTORED')
        self.assertFalse(self.backend.active)
