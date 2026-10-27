from copy import deepcopy
import unittest

from compatibility.mountinfo import parse_mountinfo
from compatibility.tests.fixtures import profile
from home.adapters.directory_takeover import HomeDirectoryTakeover
from home.adapters.native_standin import NativeHomeStandin
from home.adapters.qml_redirect import QmlRedirect
from home.lifecycle.sam_client import SamLifecycleClient
from home.operations.boot_guard import boot_allowed
from home.operations.mount_manager import Ownership, verify_ownership
from home.operations.transaction import HomeTransaction
from installer.errors import InstallerError
from installer.plan import fresh_trial


class SimulatedDevice:
    def __init__(self):
        self.journal = None
        self.active = []
        self.events = []
        self.fail_action = None
        self.rollback_failure = False
        self.health_result = {'H' + str(level): True for level in range(5)}

    def preflight(self, plan):
        self.events.append('preflight')

    def write_device_journal(self, journal):
        self.journal = deepcopy(journal)

    def execute(self, operation):
        if self.journal['events'][-1]['state'] != 'INTENT':
            raise AssertionError('Mutation occurred without a durable intent')
        action = operation['action']
        self.events.append(action)
        if action == self.fail_action:
            raise InstallerError('SIMULATED_FAILURE', 'Synthetic fault.', 5)
        self.active.append(operation)
        return {'armed': True, 'recoverySelfTestPassed': True}

    def integrity(self, plan):
        return True

    def health(self, plan):
        return deepcopy(self.health_result)

    def restore_owned(self, event, record):
        if self.rollback_failure:
            raise InstallerError('SIMULATED_BUSY_MOUNT', 'Synthetic busy mount.', 6)
        if event['operation'] in self.active:
            self.active.remove(event['operation'])

    def verify_stock(self, plan):
        return not self.active

    def reboot_verified(self, plan):
        return True

    def verify_recovery_identity(self, record):
        return True


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.device = SimulatedDevice()
        self.plan = QmlRedirect().build_plan(profile())
        self.transaction = HomeTransaction(self.plan, self.device)

    def test_trial_journals_each_mutation_and_arms_before_mount(self):
        self.transaction.stage()
        self.transaction.activate()
        self.assertLess(self.device.events.index('arm-independent-watchdog'), self.device.events.index('bind-qml-trial'))
        self.assertEqual(self.device.journal['state'], 'TRIAL_ACTIVE')

    def test_ht10_launch_acceptance_without_visible_ui_rolls_back(self):
        self.transaction.stage()
        self.transaction.activate()
        self.device.health_result['H4'] = False
        with self.assertRaises(InstallerError):
            self.transaction.verify()
        self.assertFalse(self.device.active)
        self.assertEqual(self.device.journal['state'], 'RESTORED')

    def test_ht14_activation_failure_recovers_using_device_journal(self):
        self.transaction.stage()
        self.device.fail_action = 'bind-qml-trial'
        with self.assertRaises(InstallerError):
            self.transaction.activate()
        self.assertEqual(self.device.journal['state'], 'RESTORED')

    def test_ht15_interrupted_rollback_can_resume_without_approval_digest(self):
        self.transaction.stage()
        self.transaction.activate()
        self.device.rollback_failure = True
        with self.assertRaises(InstallerError):
            self.transaction.restore()
        record = deepcopy(self.device.journal)
        self.assertEqual(record['state'], 'MANUAL_RECOVERY_REQUIRED')
        self.device.rollback_failure = False
        resumed = HomeTransaction(self.plan, self.device)
        resumed.recover(record)
        self.assertFalse(self.device.active)
        resumed.restore()

    def test_ht31_commit_requires_completed_independent_restore(self):
        self.transaction.stage()
        self.transaction.activate()
        self.transaction.verify()
        with self.assertRaises(InstallerError):
            self.transaction.commit(None, self.plan['approvalDigest'])

    def test_restored_trial_cannot_be_committed(self):
        self.transaction.stage()
        self.transaction.activate()
        self.transaction.verify()
        self.transaction.restore()
        proof = self.transaction.restoration_proof()
        with self.assertRaises(InstallerError):
            self.transaction.commit(proof, self.plan['approvalDigest'])

    def test_second_clean_trial_requires_same_artifact_and_new_transaction(self):
        self.transaction.stage()
        self.transaction.activate()
        self.transaction.verify()
        self.transaction.restore()
        proof = self.transaction.restoration_proof()
        second_plan = fresh_trial(self.plan, 'a' * 32)
        second = HomeTransaction(second_plan, self.device)
        second.stage()
        second.activate()
        second.verify()
        second.commit(proof, second_plan['approvalDigest'])
        self.assertEqual(self.device.journal['state'], 'COMMITTED')

    def test_ht16_firmware_change_blocks_boot(self):
        device = profile()
        self.assertTrue(boot_allowed(device, self.plan, self.plan['artifactDigest'], False, 0, True))
        device['identity']['firmware'] = 'UPDATED'
        self.assertFalse(boot_allowed(device, self.plan, self.plan['artifactDigest'], False, 0, True))

    def test_ht17_missing_payload_and_circuit_breaker_block_boot(self):
        for digest, failures, recovery in [('', 0, True), (self.plan['artifactDigest'], 2, True), (self.plan['artifactDigest'], 0, False)]:
            self.assertFalse(boot_allowed(profile(), self.plan, digest, False, failures, recovery))

    def test_ht06_unknown_native_abi_refused(self):
        device = profile()
        device['home']['implementation'] = 'native'
        device['identity']['architecture'] = None
        with self.assertRaises(InstallerError):
            NativeHomeStandin().build_plan(device)

    def test_ht08_web_unknown_manifest_rejected_without_mutation(self):
        device = profile()
        device['home']['implementation'] = 'web'
        with self.assertRaises(InstallerError):
            HomeDirectoryTakeover().build_plan(device)

    def test_directory_plan_checks_manager_before_releasing_old_home(self):
        device = profile()
        device['home']['implementation'] = 'web'
        device['capabilities']['samManifestReload'] = 'available'
        operations = [item['action'] for item in HomeDirectoryTakeover().build_plan(device)['operations']]
        self.assertLess(operations.index('verify-manager-manifest'), operations.index('release-old-home'))


class MountOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.baseline = '50 1 179:53 / /tmp/checkpoint/com.webos.app.fullhome rw - ext4 /dev/mmcblk0p53 rw\n'
        self.owned = '80 50 179:53 /wiios/mask /tmp/checkpoint/com.webos.app.fullhome ro - ext4 /dev/mmcblk0p53 rw\n'
        self.record = Ownership('/wiios/mask', '/tmp/checkpoint/com.webos.app.fullhome', 80, '179:53', '/wiios/mask',
                                'mnt:[1]', 'boot-1', '179:53:456', tuple(m.to_dict() for m in parse_mountinfo(self.baseline)))

    def verify(self, text, namespace='mnt:[1]', boot='boot-1'):
        return verify_ownership(self.record, parse_mountinfo(text), namespace, boot, '179:53:456', '179:53:456')

    def test_legitimate_ext4_predecessor_is_not_owned_bind(self):
        self.assertEqual(self.verify(self.baseline + self.owned).mountId, 80)
        with self.assertRaises(InstallerError):
            self.verify(self.baseline)

    def test_foreign_stack_and_nested_mount_rejected(self):
        for extra in ['81 80 0:1 /other /tmp/checkpoint/com.webos.app.fullhome ro - tmpfs tmpfs rw\n',
                      '81 80 0:1 /other /tmp/checkpoint/com.webos.app.fullhome/nested ro - tmpfs tmpfs rw\n']:
            with self.assertRaises(InstallerError):
                self.verify(self.baseline + self.owned + extra)

    def test_ht35_namespace_and_boot_change_rejected(self):
        for namespace, boot in [('mnt:[2]', 'boot-1'), ('mnt:[1]', 'boot-2')]:
            with self.assertRaises(InstallerError):
                self.verify(self.baseline + self.owned, namespace, boot)


class LifecycleTests(unittest.TestCase):
    def test_v1_message_and_v2_event_are_distinct(self):
        for contract, field in [('register-app-v2', 'event'), ('register-native-app-v1', 'message')]:
            client = SamLifecycleClient(contract)
            client.receive({'returnValue': True, field: 'registered'})
            self.assertTrue(client.registered)
            self.assertNotEqual(client.visibility(False, True), 'VISIBLE')
            self.assertEqual(client.visibility(True, True), 'VISIBLE')
            client.receive({'returnValue': False})
            self.assertEqual(client.state, 'FAILED')
